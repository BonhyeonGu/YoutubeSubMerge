import os
import datetime
import json
from flask import Flask, render_template_string, redirect, render_template, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import deepl
import pysftp

app = Flask(__name__)

def jsonTrans(srt_json):
    translator = deepl.Translator(inpJson["deepl_auth_key"])
    for i in srt_json:
        i["text"] = translator.translate_text(i["text"], target_lang="KO")
    return

def json2srt(data):
    srt_content = ""
    for index, entry in enumerate(data):
        srt_content += f"{index + 1}\n"
        start = datetime.timedelta(seconds=entry['start'])
        end = start + datetime.timedelta(seconds=entry['duration'])
        start_str = str(int(start.total_seconds() // 3600)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 60)).zfill(2) + ',' + \
                    str(int(start.microseconds / 1000)).zfill(3)
        end_str = str(int(end.total_seconds() // 3600)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 60)).zfill(2) + ',' + \
                  str(int(end.microseconds / 1000)).zfill(3)
        srt_content += f"{start_str} --> {end_str}\n{entry['text']}\n\n"
    return srt_content

def mergeSource(vName, srtName, outName):
    global inpJson
    cmd = f"ffmpeg -loglevel fatal -y -i {vName} -vf \"subtitles={srtName}:fontsdir=/root/p:force_style='Fontname={inpJson['fontname']},Alignment=2,MarginV=30'\" -c:a copy {outName}"
    os.system(cmd)
    return

def sanitize_filename(name, max_length=255):
    return name[:max_length].rsplit(' ', 0)[0]

def routine(video_url: str, video_id: str, la: str):
    vName = f'{video_id}.mp4'
    srtName = f'{video_id}.srt'
    outName = f'{video_id}_final.mp4'
    
    vName = sanitize_filename(vName)
    outName = sanitize_filename(outName)

    print(f"Downloading video from {video_url}")
    os.system(f"wget -O {vName} {video_url}")
    print("Download End")
    
    try:
        print(f"Try : {video_id} --- {la}")
        if la == 'zh': 
            srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-Hans', 'zh-Hant'])
        else:
            srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=[la])
        
        if la != 'ko':  
            jsonTrans(srt_json)

    except Exception as e:
        print(f"Except! : {e}")
        
        try:
            srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko'])
        except NoTranscriptFound as e:
            try:
                srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                jsonTrans(srt_json)
            except NoTranscriptFound as e:
                try: 
                    srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja'])
                    jsonTrans(srt_json)
                except:
                    return False

    srt = json2srt(srt_json)
    with open(srtName, 'w', encoding='utf-8') as f:
        f.write(str(srt))

    print(f"FFMPEG Start")
    mergeSource(vName, srtName, outName)
    print(f"FFMPEG End")
    os.remove(vName)
    os.remove(srtName)  

    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None

    host = inpJson["sftp"]["host"]
    port = inpJson["sftp"]["port"]
    id = inpJson["sftp"]["id"]
    pw = inpJson["sftp"]["pw"]
    sftpOutLocale = inpJson["sftp"]["locale"]

    sftp_target_name = f"{video_id}.mp4"

    with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
        sftp.put(f"./{outName}", f"{sftpOutLocale}{sftp_target_name}")
        print(f"Uploaded {outName} as {sftp_target_name} to SFTP")
    
    os.remove(outName)
    return True

@app.route('/subsc', methods=['POST'])
def subscribe():
    data = request.get_json()
    video_url = data.get('url')
    video_id = data.get('id')
    la = data.get('language')
    print(f"Input : {video_url} --- {video_id} - {la}")
    success = routine(video_url, video_id, la)
    if success:
        return jsonify({"success": True, "message": "Subscription successful"}), 200
    else:
        return jsonify({"success": False, "message": "Subscription failed"}), 500

@app.route('/getremotelist', methods=['GET'])
def list_files():
    ret = []
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
    host = inpJson["sftp"]["host"]
    port = inpJson["sftp"]["port"]
    id = inpJson["sftp"]["id"]
    pw = inpJson["sftp"]["pw"]
    sftpOutLocale = inpJson["sftp"]["locale"]
    try:
        with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
            sftp.cwd(sftpOutLocale)
            directory_attributes = sftp.listdir_attr()
            for attr in directory_attributes:
                ret.append(f"이름: {attr.filename}, 크기: {attr.st_size}, 수정 날짜: {attr.st_mtime}")
    except Exception as e:
        print(f"연결 중 에러 발생: {e}")
    return jsonify(ret)

@app.route('/deleteremote', methods=['POST'])
def delete_file():
    data = request.get_json()
    if data:
        video_id = data.get('videoId')
        if not video_id:
            return jsonify({"error": "videoId가 전달되지 않았습니다."}), 400

        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None

        host = inpJson["sftp"]["host"]
        port = inpJson["sftp"]["port"]
        id = inpJson["sftp"]["id"]
        pw = inpJson["sftp"]["pw"]
        sftpOutLocale = inpJson["sftp"]["locale"]

        fileLocale = os.path.join(sftpOutLocale, video_id + '.mp4')
        
        try:
            with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
                try:
                    sftp.stat(fileLocale)
                    sftp.remove(fileLocale)
                    return jsonify({"message": "삭제 성공"}), 200
                except FileNotFoundError:
                    return jsonify({"error": "파일 찾지 못함"}), 400
        except Exception as e:
            return jsonify({"error": "서버 오류 발생", "details": str(e)}), 500
    else:
        return jsonify({"error": "변수 전달 받지 못함"}), 400

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    global inpJson
    with open('./youtubeEasyDownloader.json', 'r') as f:
        inpJson = json.load(f)
    app.run(host='0.0.0.0', port=5000)

import os
import datetime
import json
from flask import Flask, render_template_string, redirect, render_template, request, jsonify
from pytubefix import YouTube
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
import deepl
import pysftp

def jsonTrans(srt_json):
    global inpJson
    translator = deepl.Translator(inpJson["deepl_auth_key"])
    for i in srt_json:
        i["text"] = translator.translate_text(i["text"], target_lang="KO")
    return

def json2srt(data):
    srt_content = ""
    for index, entry in enumerate(data):
        # 자막 번호 추가
        srt_content += f"{index + 1}\n"

        # 시작 시간과 종료 시간 계산
        start = datetime.timedelta(seconds=entry['start'])
        end = start + datetime.timedelta(seconds=entry['duration'])

        # 시간 형식 변환 (시:분:초,밀리초)
        start_str = str(int(start.total_seconds() // 3600)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 60)).zfill(2) + ',' + \
                    str(int(start.microseconds / 1000)).zfill(3)
        end_str = str(int(end.total_seconds() // 3600)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 60)).zfill(2) + ',' + \
                  str(int(end.microseconds / 1000)).zfill(3)

        # 자막 텍스트와 함께 SRT 형식으로 추가
        srt_content += f"{start_str} --> {end_str}\n{entry['text']}\n\n"
    return srt_content

def mergeSource(vName, aName, srtName, outName):
    global inpJson
    # cmd = f'ffmpeg -i {vName} -i {aName} -i {srtName} -c:v copy -c:a aac -strict experimental -c:s mov_text -map 0:v -map 1:a -map 2:s {outName}' #내장식
    # cmd = f'ffmpeg -loglevel fatal -y -i {vName} -i {aName} -vf "subtitles={srtName}:fontsdir=/root/p:force_style=\'Fontname={inpJson["fontname"]}\'" -c:a aac -strict experimental {outName}'
    cmd = f"ffmpeg -loglevel fatal -y -i {vName} -i {aName} -vf \"subtitles={srtName}:fontsdir=/root/p:force_style='Fontname={inpJson['fontname']},Alignment=2,MarginV=30'\" -c:a aac -strict experimental {outName}"

    os.system(cmd)
    return

def sanitize_filename(name, max_length=255):
    #파일 이름 자르기
    return name[:max_length].rsplit(' ', 0)[0]

def routine(video_id: str, la: str):
    global inpJson

    vName = f'{video_id}_Video.mp4'
    aName = f'{video_id}_Audio.mp4'
    srtName = f'{video_id}.srt'
    outName = f'{video_id}.mp4'
    
    video_url = f'https://www.youtube.com/watch?v={video_id}'
    yt = YouTube(video_url)
    vName = sanitize_filename(vName)
    aName = sanitize_filename(aName)
    outName = sanitize_filename(outName)
    
    dName = yt.streams.filter(adaptive=True, file_extension='mp4').first().download(filename=vName)
    os.rename(dName, vName)
    dName = yt.streams.filter(only_audio=True).first().download(filename=aName)
    os.rename(dName, aName)
    try:
        srt_json = YouTubeTranscriptApi.get_transcript(video_id, languages=[la])
        if la != 'ko':
            jsonTrans(srt_json)
    except:
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
    srtName = f'{video_id}.srt'
    with open(srtName, 'w', encoding='utf-8') as f:
        f.write(str(srt))
    #배열에 text
    mergeSource(vName, aName, srtName, outName)
    os.remove(vName)
    os.remove(aName)
    os.remove(srtName)  

    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None

    host = inpJson["sftp"]["host"]
    port = inpJson["sftp"]["port"]
    id = inpJson["sftp"]["id"]
    pw = inpJson["sftp"]["pw"]
    sftpOutLocale = inpJson["sftp"]["locale"]
    with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
        sftp.put(f"./{outName}", f"{sftpOutLocale}{outName}")
    os.remove(outName)
    return True

def getRemoteList():
    global inpJson
    ret = list()
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

    return ret

app = Flask(__name__)

@app.route('/subsc/')
def info():
    return render_template_string("<html><body><h1>/subsc/[id]</h1></body></html>")

@app.route('/subsc/<id>/<la>')
def subscribe(id, la):
    global inpJson

    success = routine(id, la)
    # 성공 여부에 따른 응답 반환
    if success:
        return jsonify({"success": True, "message": "Subscription successful"}), 200
    else:
        return jsonify({"success": False, "message": "Subscription failed"}), 500

@app.route('/getremotelist', methods=['GET'])
def list_files():
    file_list = getRemoteList()
    return jsonify(file_list)

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
                    # 파일이 존재하는지 시도해봄
                    sftp.stat(fileLocale)
                    sftp.remove(fileLocale)
                    return jsonify({"message": "삭제 성공"}), 200
                except FileNotFoundError:
                    # 파일이 존재하지 않음
                    return jsonify({"error": "파일 찾지 못함"}), 400
        except Exception as e:
            # 그 외 예외 처리
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

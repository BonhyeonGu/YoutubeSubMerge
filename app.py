import os
import datetime
import json
from flask import Flask, render_template_string, redirect, render_template, request, jsonify
import deepl
import pysftp
import subprocess
import re

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024

def print_transcript_languages(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        print(f"[INFO] 자막 가능한 언어 목록 (video_id = {video_id}):")
        for transcript in transcript_list:
            lang_code = transcript.language_code
            lang_name = transcript.language
            is_generated = transcript.is_generated
            print(f" - [{lang_code}] {lang_name} (자동 생성: {is_generated})")

    except TranscriptsDisabled:
        print("[ERROR] 이 영상은 자막이 비활성화되어 있습니다.")
    except NoTranscriptFound:
        print("[ERROR] 이 영상에 자막이 없습니다.")
    except Exception as e:
        print(f"[ERROR] 예기치 못한 오류: {e}")

def fetch_transcript_by_language(video_id: str, target_language_prefix: str):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        for transcript in transcript_list:
            lang_code = transcript.language_code
            if lang_code.startswith(target_language_prefix):  # 'ko', 'en' 등
                try:
                    return transcript.fetch()
                except Exception as fetch_err:
                    print(f"[WARN] fetch 실패 ({lang_code}): {fetch_err}")
        print(f"[ERROR] 언어 코드가 '{target_language_prefix}'로 시작하는 자막이 없습니다.")
        return None
    except Exception as e:
        print(f"[ERROR] 자막 리스트 조회 실패: {e}")
        return None


def extract_video_id(video_id_or_url: str) -> str:
    input_str = video_id_or_url.strip()

    # 이미 video ID만 들어온 경우
    if re.fullmatch(r"^[a-zA-Z0-9_-]{11}$", input_str):
        return input_str

    # URL에서 v= 파라미터로 추출
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", input_str)
    if match:
        return match.group(1)

    raise ValueError(f"[ERROR] 유효한 YouTube video ID 또는 URL이 아닙니다: {video_id_or_url}")

def jsonTrans(srt_json):
    translator = deepl.Translator(inpJson["deepl_auth_key"])
    for i in srt_json:
        i.text = translator.translate_text(i.text, target_lang="KO")
    return

def json2srt(data):
    srt_content = ""
    for index, entry in enumerate(data):
        srt_content += f"{index + 1}\n"
        start = datetime.timedelta(seconds=entry.start)
        end = start + datetime.timedelta(seconds=entry.duration)
        start_str = str(int(start.total_seconds() // 3600)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                    str(int(start.total_seconds() % 60)).zfill(2) + ',' + \
                    str(int(start.microseconds / 1000)).zfill(3)
        end_str = str(int(end.total_seconds() // 3600)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 3600 // 60)).zfill(2) + ':' + \
                  str(int(end.total_seconds() % 60)).zfill(2) + ',' + \
                  str(int(end.microseconds / 1000)).zfill(3)
        srt_content += f"{start_str} --> {end_str}\n{entry.text}\n\n"
    return srt_content

def mergeSource(vName, srtName, outName):
    global inpJson
    cmd = f"ffmpeg -loglevel fatal -y -i {vName} -vf \"subtitles={srtName}:fontsdir=/root/p:force_style='Fontname={inpJson['fontname']},Alignment=2,MarginV=30'\" -c:a copy {outName}"
    os.system(cmd)
    return

def sanitize_filename(name, max_length=255):
    return name[:max_length].rsplit(' ', 0)[0]

def routine(video_url: str, video_id: str, la: str):
    video_id = extract_video_id(video_id)
    vName = sanitize_filename(f'{video_id}.mp4')
    srtName = f'{video_id}.srt'
    outName = sanitize_filename(f'{video_id}_final.mp4')

    print_transcript_languages(video_id)

    print(f"[DOWNLOAD] Downloading video from {video_url}")
    subprocess.run(["wget", "-O", vName, video_url], check=True)
    print("[DOWNLOAD] Download complete.")

    print(f"[TRANSCRIPT] Attempting to fetch transcript for language: {la}")
    srt_json = fetch_transcript_by_language(video_id, la)

    if not srt_json:
        raise RuntimeError(f"[TRANSCRIPT] Failed to fetch transcript for {video_id} in {la}.")

    if la != 'ko':
        print("[TRANSLATE] Translating transcript to Korean...")
        jsonTrans(srt_json)
        print("[TRANSLATE] Translation complete.")

    print("[TRANSCRIPT] Generating SRT file...")
    srt = json2srt(srt_json)
    with open(srtName, 'w', encoding='utf-8') as f:
        f.write(srt)
    print(f"[TRANSCRIPT] SRT file {srtName} created.")

    print("[FFMPEG] Starting merge with subtitles...")
    mergeSource(vName, srtName, outName)
    print("[FFMPEG] Merge complete.")

    os.remove(vName)
    os.remove(srtName)
    print("[CLEANUP] Temporary files removed.")

    print("[SFTP] Starting upload to remote server...")
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None

    host = inpJson["sftp"]["host"]
    port = inpJson["sftp"]["port"]
    id = inpJson["sftp"]["id"]
    pw = inpJson["sftp"]["pw"]
    sftpOutLocale = inpJson["sftp"]["locale"]
    sftp_target_name = f"{video_id}.mp4"

    with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
        sftp.put(outName, os.path.join(sftpOutLocale, sftp_target_name))
        print(f"[SFTP] Uploaded {outName} as {sftp_target_name} to SFTP.")

    os.remove(outName)
    print("[CLEANUP] Final file removed.")
    print("[SUCCESS] Routine completed successfully.")
    return True

def routine_for_upload(vName: str, video_id: str, la: str):
    video_id = extract_video_id(video_id)
    srtName = f'{video_id}.srt'
    outName = f'{video_id}_final.mp4'
    print_transcript_languages(video_id)

    print(f"[UPLOAD] Processing uploaded video: {vName}")

    # 사용자 선택 언어만 시도
    try:
        print(f"[UPLOAD] Trying YouTubeTranscriptApi for language: {la}")
        srt_json = fetch_transcript_by_language(video_id, la)
        print("[UPLOAD] Transcript fetched successfully!")
    except Exception as e:
        print(f"[UPLOAD] Transcript fetch error for {la}: {e}")
        raise RuntimeError(f"[UPLOAD] Failed to fetch transcript for {video_id} in {la}.")

    if la != 'ko':
        print("[UPLOAD] Translating transcript to Korean...")
        jsonTrans(srt_json)
        print("[UPLOAD] Translation done!")

    print("[UPLOAD] Creating SRT file...")
    srt = json2srt(srt_json)
    with open(srtName, 'w', encoding='utf-8') as f:
        f.write(srt)
    print(f"[UPLOAD] SRT file {srtName} created.")

    print("[UPLOAD] Starting FFMPEG merge...")
    mergeSource(vName, srtName, outName)
    print("[UPLOAD] FFMPEG merge done.")

    os.remove(srtName)
    os.remove(vName)
    print("[UPLOAD] Temporary files deleted.")

    print("[UPLOAD] Starting SFTP upload...")
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
    host = inpJson["sftp"]["host"]
    port = inpJson["sftp"]["port"]
    id = inpJson["sftp"]["id"]
    pw = inpJson["sftp"]["pw"]
    sftpOutLocale = inpJson["sftp"]["locale"]

    with pysftp.Connection(host, port=port, username=id, password=pw, cnopts=cnopts) as sftp:
        sftp.put(outName, os.path.join(sftpOutLocale, f"{video_id}.mp4"))
        print(f"[UPLOAD] Uploaded {outName} as {video_id}.mp4 to SFTP.")

    os.remove(outName)
    print("[UPLOAD] All done successfully!")
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

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    video_id = request.form['id']
    video_id = extract_video_id(video_id)
    language = request.form['language']

    if file and video_id:
        filename = f"{video_id}.mp4"
        file.save(filename)
        print(f"File {filename} uploaded.")

        # 이후 처리: 번역 및 sftp 업로드 (routine 함수의 변형)
        success = routine_for_upload(filename, video_id, language)

        if success:
            return jsonify({"success": True, "message": "파일 업로드 및 처리 완료"}), 200
        else:
            return jsonify({"success": False, "message": "처리 중 오류 발생"}), 500

    return jsonify({"error": "파일 또는 ID가 누락됨"}), 400



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

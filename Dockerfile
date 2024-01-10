FROM ubuntu:20.04
LABEL email="bonhyeon.gu@9bon.org"
LABEL name="BonhyeonGu"
ENV TZ=Asia/Seoul
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get upgrade -y && apt update
RUN apt install -y ffmpeg
#Time-------------------------------------------------------
RUN apt-get install -y git tzdata python3 python3-pip nano tmux
RUN pip3 install pysftp youtube-transcript-api pytube flask
RUN echo $TZ > /etc/timezone && \
    rm /etc/localtime && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean
#-----------------------------------------------------------
RUN apt-get install -y wget
RUN wget -O /usr/share/fonts/NanumGothic.ttf "경로"
#-----------------------------------------------------------
WORKDIR /root
RUN git clone https://github.com/BonhyeonGu/YoutubeEasyDownloader p

WORKDIR /root/p/
COPY ./youtubeEasyDownloader.json ./
ENTRYPOINT ["/bin/sh", "-c" , "tail -f /dev/null"]
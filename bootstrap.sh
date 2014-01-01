#!/usr/bin/env bash

apt-get update

sudo apt-get -y install libtool
sudo apt-get -y install python-dev libyaml-dev
sudo apt-get -y install python-pip

pip install pyyaml
pip install feedparser
pip install beautifulsoup4
pip install praw
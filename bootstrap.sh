#!/usr/bin/env bash

apt-get update

sudo apt-get -y install libtool
sudo apt-get -y install python-dev libyaml-dev
sudo apt-get -y install python-pip

pip install -r /vagrant/requirements.txt

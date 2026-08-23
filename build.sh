#!/usr/bin/env bash
set -o errexit

# Install Tesseract OCR with French and Arabic language packs
apt-get update -qq
apt-get install -y -qq tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara

# Install Python dependencies
pip install -r requirements.txt

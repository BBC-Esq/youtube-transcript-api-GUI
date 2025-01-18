import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QLineEdit, QComboBox, QPushButton, QLabel, QMessageBox,
                              QHBoxLayout)
from PySide6.QtCore import QThread, Signal
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import (JSONFormatter, PrettyPrintFormatter, 
                                             TextFormatter, WebVTTFormatter, SRTFormatter)
import requests

FORMAT_TOOLTIP = """
Output Format Options:

JSON (.json): Machine-readable format with precise decimal timing (e.g., "start": 0.32).
Ideal for data processing and APIs.

SRT (.srt): Standard subtitle format using timestamp ranges (00:00:00,320).
Widely supported by video players.

WebVTT (.vtt): Modern HTML5 caption format similar to SRT but uses periods
for milliseconds. Includes WEBVTT header.

Pretty Print (.txt): Human-readable Python data structure format with proper
indentation. Useful for debugging.

Text (.txt): Simple plain text format with just the transcript content.
"""

class TranscriptListWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def get_video_id(self, youtube_url):
        parsed_url = urlparse(youtube_url)
        
        if 'youtu.be' in parsed_url.netloc:
            return parsed_url.path[1:]
        elif 'youtube.com' in parsed_url.netloc:
            if 'shorts' in parsed_url.path:
                return parsed_url.path.split('/')[-1]
            else:
                return parse_qs(parsed_url.query)['v'][0]
        return None

    def run(self):
        try:
            video_id = self.get_video_id(self.url)
            if not video_id:
                self.error.emit("Could not extract video ID from URL")
                return

            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            self.finished.emit(transcript_list)

        except Exception as e:
            self.error.emit(str(e))

class TranscriptWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url, formatter_name):
        super().__init__()
        self.url = url
        self.formatter_name = formatter_name

    def get_video_id(self, youtube_url):
        parsed_url = urlparse(youtube_url)
        
        if 'youtu.be' in parsed_url.netloc:
            return parsed_url.path[1:]
        elif 'youtube.com' in parsed_url.netloc:
            if 'shorts' in parsed_url.path:
                return parsed_url.path.split('/')[-1]
            else:
                return parse_qs(parsed_url.query)['v'][0]
        return None

    def get_video_title(self, video_id):
        try:
            url = f"https://www.youtube.com/oembed?url=http://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(url)
            return response.json()['title']
        except:
            return video_id

    def sanitize_filename(self, title):
        invalid_chars = '<>:"/\\|?*'
        filename = ''.join(char for char in title if char not in invalid_chars)
        return filename[:50]

    def run(self):
        try:
            video_id = self.get_video_id(self.url)
            if not video_id:
                self.error.emit("Could not extract video ID from URL")
                return

            video_title = self.get_video_title(video_id)
            safe_title = self.sanitize_filename(video_title)

            # Get transcript without specifying language
            transcript = YouTubeTranscriptApi.get_transcript(video_id)

            formatters = {
                'JSON': (JSONFormatter(), 'json'),
                'Pretty Print': (PrettyPrintFormatter(), 'txt'),
                'Text': (TextFormatter(), 'txt'),
                'WebVTT': (WebVTTFormatter(), 'vtt'),
                'SRT': (SRTFormatter(), 'srt')
            }

            formatter, ext = formatters[self.formatter_name]
            formatted_transcript = formatter.format_transcript(transcript)
            
            filename = f"{safe_title}.{ext}"
            
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(formatted_transcript)

            self.finished.emit(filename)

        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Transcript Extractor")
        self.setMinimumWidth(600)
        self.transcript_list = None

        # Main widget and layout
        main_widget = QWidget()
        layout = QVBoxLayout()

        # URL input and Check Transcripts button in horizontal layout
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste YouTube URL here")
        self.check_button = QPushButton("Check Available Transcripts")
        self.check_button.clicked.connect(self.check_transcripts)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.check_button)
        layout.addWidget(QLabel("YouTube URL:"))
        layout.addLayout(url_layout)

        # Native language selection
        self.language_combo = QComboBox()
        layout.addWidget(QLabel("Available Transcripts:"))
        layout.addWidget(self.language_combo)

        # Translation language selection
        self.translation_combo = QComboBox()
        layout.addWidget(QLabel("Available Translations (not yet implemented, will come in a future release):"))
        layout.addWidget(self.translation_combo)

        # Formatter selection
        formatter_label = QLabel("Output Format:")
        formatter_label.setToolTip(FORMAT_TOOLTIP)
        self.formatter_combo = QComboBox()
        self.formatter_combo.addItems(['JSON', 'Pretty Print', 'Text', 'WebVTT', 'SRT'])
        self.formatter_combo.setToolTip(FORMAT_TOOLTIP)
        layout.addWidget(formatter_label)
        layout.addWidget(self.formatter_combo)

        # Convert button
        self.convert_button = QPushButton("Obtain Transcript")
        self.convert_button.clicked.connect(self.start_conversion)
        self.convert_button.setEnabled(False)
        layout.addWidget(self.convert_button)

        # Status label
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)

    def check_transcripts(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter a YouTube URL")
            return

        self.check_button.setEnabled(False)
        self.status_label.setText("Checking available transcripts...")
        self.language_combo.clear()
        self.translation_combo.clear()

        self.list_worker = TranscriptListWorker(url)
        self.list_worker.finished.connect(self.on_transcript_list_received)
        self.list_worker.error.connect(self.on_error)
        self.list_worker.start()

    def start_conversion(self):
        url = self.url_input.text().strip()
        
        self.convert_button.setEnabled(False)
        self.status_label.setText("Obtaining transcript...")

        self.worker = TranscriptWorker(url, self.formatter_combo.currentText())
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_transcript_list_received(self, transcript_list):
        self.transcript_list = transcript_list
        self.language_combo.clear()
        self.translation_combo.clear()

        # Add available transcripts to first combo box
        languages = []
        for transcript in transcript_list:
            languages.append(f"{transcript.language} ({transcript.language_code})")
        self.language_combo.addItems(languages)

        # Add translation languages to second combo box if translatable
        for transcript in transcript_list:
            if transcript.is_translatable:
                translation_languages = [
                    f"{lang['language']} ({lang['language_code']})" 
                    for lang in transcript.translation_languages
                ]
                self.translation_combo.addItems(translation_languages)

        self.convert_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.status_label.setText("Ready to convert")

    def on_conversion_finished(self, filename):
        self.status_label.setText(f"Saved as: {filename}")
        self.convert_button.setEnabled(True)
        QMessageBox.information(self, "Success", f"Transcript saved as:\n{filename}")

    def on_error(self, error_message):
        self.status_label.setText("Error occurred")
        self.check_button.setEnabled(True)
        self.convert_button.setEnabled(False)
        QMessageBox.critical(self, "Error", f"An error occurred:\n{error_message}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
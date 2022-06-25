import sys
# from tkinter import *
# from tkinter import filedialog, messagebox
# from tkinter.ttk import *
import instaloader
from instaloader.structures import Hashtag, load_structure_from_file
import os
# import signal
from pathlib import Path
# from multiprocessing import Process
import csv

from PyQt5 import uic
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from PyQt5.QtWidgets import QDialog, QApplication, QFileDialog, QMessageBox

INSTA_DOWNLOAD_PROGRESS = 40

INSTA_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'insta_dialog.ui'))

class InstaDialog(QDialog, INSTA_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.confFilePath = os.path.join(os.path.dirname(__file__), "instaloader.conf")

        self.ELEM_VAR_MAP = {
            'USERNAME'  :   self.username,
            'PASSWORD'  :   self.password,
            'HASHTAG'   :   self.hashtag,
            'OUTPUTDIR' :   self.outputDir,
            'NUMROWS'   :   self.numrows
        }

        self.startBtn.clicked.connect(self._start_download_thread)
        self.stopBtn.clicked.connect(self._stop_download_thread)

        self.outputDirPicker.clicked.connect(self._select_output_folder)

        self._load()

        self.progressBar.setValue(0)
        self.progressBar.setMaximum(100)


    def _select_output_folder(self):
        outputDir = QFileDialog.getExistingDirectory(self, "choose output directory")
        self.outputDir.setText(outputDir)
        
    def _load(self):
        if os.path.exists(self.confFilePath):
            f = open(self.confFilePath, 'r')

            for line in f.readlines():
                key, val = line.strip('\n').split('=')
                elem = self.ELEM_VAR_MAP[key]
                elem.setText(val)

            f.close()

    def _save(self):
        f = open(self.confFilePath, 'w')

        l = [f"{key}={elem.text()}" for key, elem in self.ELEM_VAR_MAP.items()]

        f.write('\n'.join(l))
        f.close()

    def _start_download_thread(self):
        self._save()
        self.progressBar.setValue(0)

        self.startBtn.setEnabled(False)
        self.stopBtn.setEnabled(True)

        username = self.username.text()
        password = self.password.text()
        hashtag = self.hashtag.text()
        dirname = self.outputDir.text()
        numrows = self.numrows.text()

        try:
            numrows = int(numrows)
        except Exception as ex:
            QMessageBox.warning(self, "invalid number of rows", ex)

        self.thread = QThread()
        self.worker = InstaWorker(username, password, dirname, hashtag, numrows)
        self.worker.moveToThread(self.thread)

        self.worker.addError.connect(self._error_from_worker)
        self.worker.progress.connect(self._progress_from_worker)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        def worker_finished():
            self.startBtn.setEnabled(True)
            self.stopBtn.setEnabled(False)
            print('worker finished')
            self.progressBar.setValue(self.progressBar.maximum())

        self.worker.finished.connect(worker_finished)

        self.thread.start()

    def _stop_download_thread(self):
        if hasattr(self, 'worker'):
            self.worker.stop()

    def _error_from_worker(self, message):
        QMessageBox.warning(self, "Error", message)

    def _progress_from_worker(self, progress):
        self.progressBar.setValue(int(progress))


class InstaWorker(QObject):
    addError = pyqtSignal()
    finished = pyqtSignal()
    progress = pyqtSignal(float)

    def __init__(self, username, password, dirname, hashtag, numrows):
        QObject.__init__(self)
        self.loader = instaloader.Instaloader(
            download_pictures=True,
            download_geotags=True, 
            download_videos=False, 
            download_video_thumbnails=False, 
            download_comments=False,
            save_metadata=True,
            compress_json=False
        )
        self.username = username
        self.password = password
        self.dirname = dirname
        self.hashtag = hashtag
        self.numrows = numrows

        self.running = None

    def stop(self):
        self.running = False

    def run(self):
        print("spawned process:", os.getpid())
        self.running = True
        self._load_posts()

    def _load_posts(self):
        try:
            self.loader.login(self.username, self.password)
        except Exception as ex:
            print(ex)
            self.addError.emit(f"unsuccessful login attempt: {ex}")
            self.finished.emit()
            return
        else:
            print('logged in successfully')

        if self.hashtag[0] == '#':
            self.hashtag = self.hashtag[1:]

        if not self.running:
            self.finished.emit()
            return


        postCount = 0
        try:
            hashtagObj = Hashtag.from_name(self.loader.context, self.hashtag)
        except Exception as ex:
            print(ex)
            self.addError.emit(f"error downloading hashtag list: {ex}")
            self.finished.emit()
            return

        for post in hashtagObj.get_posts_resumable():
            self.progress.emit(INSTA_DOWNLOAD_PROGRESS * postCount / self.numrows)
            if not self.running:
                self.finished.emit()
                return
            try:
                self.loader.download_post(post, target=Path(self.dirname))
                postCount += 1
            except:
                print(f"could not download {post.shortcode}")
            else:
                print(f"downloaded {post.shortcode}")
            if postCount >= self.numrows:
                break

        print("downloaded", postCount, "posts")
        self.progress.emit(INSTA_DOWNLOAD_PROGRESS)

        self._process_posts()

        self.finished.emit()
        return

    def _process_data_file(self, json_file):
        if not self.running:
            self.finished.emit()
            return None

        post = load_structure_from_file(self.loader.context, json_file)
        filename, extension = os.path.splitext(json_file)
        captionFileName = filename + ".txt"

        if os.path.isfile(captionFileName):
            try:
                with open(captionFileName, 'r', encoding='utf-8') as captionFile:
                    caption = captionFile.read()
                print("read caption from caption file", captionFileName)
            except Exception as ex:
                print('failed to read from caption file', captionFileName)
                print(ex)
                caption = post.caption
        else:
            print(captionFileName, 'does not exist')
            caption = post.caption

        return {
            "title": post.title,
            "username": post.owner_username,
            "date": post.date_local,
            "location": post.location,
            "caption": caption,
            "hashtags": post.caption_hashtags
        }

    def _process_posts(self):
        json_files = [os.path.join(self.dirname, json_file) for json_file in os.listdir(self.dirname) if json_file.endswith('.json')]

        # json_comment_files = [json_file for json_file in json_files if json_file.endswith('_comments.json')]
        json_data_files = [json_file for json_file in json_files if not json_file.endswith('_comments.json')]

        try:
            csvFile = open(os.path.join(self.dirname, f"{self.hashtag}.csv"), 'w', encoding='utf-8')
        except:
            self.addError.emit("error opening csv file handle. please close file and try again")
            self.finished.emit()
            return

        csvWrite = csv.writer(csvFile, lineterminator='\n')

        csvWrite.writerow(["id", "username", "caption", "hashtags", "date", "lat", "lng", "location"])

        for index, json_data_file in enumerate(json_data_files):
            self.progress.emit(INSTA_DOWNLOAD_PROGRESS + (100 - INSTA_DOWNLOAD_PROGRESS) * (index + 1) / len(json_data_files))
            if not self.running:
                self.finished.emit()
                return

            data = self._process_data_file(json_data_file)
            if data is None:
                return

            loc = data['location']
            if loc != None:
                if type(loc.lat) == tuple:
                    lat = loc.lat[0]
                else:
                    lat = loc.lat,
                if type(loc.lng) == tuple:
                    lng = loc.lng[0]
                else:
                    lng = loc.lng
                location = loc.name
            else:
                lat, lng, location = '', '', ''

            row = [
                index+1, 
                data['username'], 
                data['caption'], 
                " ".join([f"#{hashtag}" for hashtag in data['hashtags']]),
                data['date'].strftime('%Y-%m-%d'), 
                str(lat) if lat is not None else '', 
                str(lng) if lng is not None else '',
                location if location is not None else ''
            ]

            csvWrite.writerow(row)

        csvFile.close()
        print('flushed data to csv file')

"""
class InstaGUI:
    def __init__(self):
        print('gui opened')
        self.confFilePath = os.path.join(os.path.dirname(__file__), "instaloader.conf")
        self._create_gui()
        self._switch_stop_btn()
        self._load()
        # self.window.protocol("WM_DELETE_WINDOW", self._stop_process)
        self.window.mainloop()

    def __del__(self):
        self._stop_process()
        print('gui closed')

    def _stop_process(self):
        if hasattr(self, 'process'):
            self.process.terminate()
            self.process.join()

    def _create_gui(self):
        self.window = Tk()
        self.window.title("Instaloader")
        self.window.geometry('330x200')

        usernameLabel = Label(self.window, text="username")
        usernameLabel.grid(column=0, row=0)

        self.usernameInput = Entry(self.window,width=40)
        self.usernameInput.grid(column=1, row=0)

        passwordLabel = Label(self.window, text="password")
        passwordLabel.grid(row=1, column=0)

        self.passwordInput = Entry(self.window,width=40)
        self.passwordInput.grid(column=1, row=1)

        hashtagLabel = Label(self.window, text="hashtag")
        hashtagLabel.grid(column=0, row=2)

        self.hashtagInput = Entry(self.window,width=40)
        self.hashtagInput.grid(column=1, row=2)

        outputdirLabel = Label(self.window, text="output folder")
        outputdirLabel.grid(column=0, row=3)

        self.outputdirInput = Entry(self.window,width=40)
        self.outputdirInput.grid(column=1, row=3)        

        numrowsLabel = Label(self.window, text="limit records")
        numrowsLabel.grid(column=0, row=4)

        self.numrowsInput = Entry(self.window,width=40)
        self.numrowsInput.grid(column=1, row=4)

        self.ELEM_VAR_MAP = {
            'USERNAME'  :   self.usernameInput,
            'PASSWORD'  :   self.passwordInput,
            'HASHTAG'   :   self.hashtagInput,
            'OUTPUTDIR' :   self.outputdirInput,
            'NUMROWS'   :   self.numrowsInput
        }

        dirBtn = Button(self.window, text = 'Set Output Directory', command = self._setOutputDir, width=50)
        dirBtn.grid(column = 0, row = 5, columnspan=2)

        saveBtn = Button(self.window, text = 'Save', command = self._save, width=50)
        saveBtn.grid(column = 0, row = 5, columnspan=2)

        self.startBtn = Button(self.window, text = 'Start', command = self._start, width=50)
        self.startBtn.grid(column = 0, row = 7, columnspan=2)

        self.stopBtn = Button(self.window, text = 'Stop', command = self._stop, width=50)
        self.stopBtn.grid(column = 0, row = 8, columnspan=2)

        progress = Progressbar(self.window, orient = HORIZONTAL, length = 300, mode = 'determinate')
        progress.grid(row=9, columnspan=2)

    def _load(self):
        if os.path.exists(self.confFilePath):
            f = open(self.confFilePath, 'r')

            for line in f.readlines():
                key, val = line.strip('\n').split('=')
                elem = self.ELEM_VAR_MAP[key]
                elem.delete(0, END)
                elem.insert(0, val)

            f.close()

    def _save(self):
        f = open(self.confFilePath, 'w')

        l = [f"{key}={elem.get()}" for key, elem in self.ELEM_VAR_MAP.items()]

        f.write('\n'.join(l))
        f.close()

    def _switch_submit_btn(self):
        if self.startBtn['state'] != 'disabled':
            self.startBtn['state'] = 'disabled'
        else:
            self.startBtn['state'] = 'normal'

    def _switch_stop_btn(self):
        print(self.stopBtn['state'])
        if self.stopBtn['state'] != 'disabled':
            self.stopBtn['state'] = 'disabled'
        else:
            self.stopBtn['state'] = 'normal'

    def _stop(self):
        if hasattr(self, 'worker'):
            self.worker.stop()

    def _start(self):
        self._save()
        self._switch_submit_btn()
        self._switch_stop_btn()

        username = self.usernameInput.get()
        password = self.passwordInput.get()
        hashtag = self.hashtagInput.get()
        dirname = self.outputdirInput.get()
        numrows = self.numrowsInput.get()

        try:
            numrows = int(numrows)
        except Exception as ex:
            messagebox.showerror("invalid number of rows", ex)


        self.thread = QThread()
        self.worker = InstaWorker(username, password, dirname, hashtag, numrows)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        def worker_finished():
            self._switch_submit_btn()
            self._switch_stop_btn()
            print('worker finished')

        self.worker.finished.connect(worker_finished)

        # start thread and run worker
        self.thread.start()
        
        # self.process = InstaProcess(username, password, dirname, hashtag, numrows)
        # self.process.start()

    def _setOutputDir(self):
        dirname = filedialog.askdirectory() 
        self.outputdirInput.delete(0, END)
        self.outputdirInput.insert(0, dirname)
"""

"""
class InstaProcess(Process):
    def __init__(self, username, password, dirname, hashtag, numrows):
        Process.__init__(self)
        self.loader = instaloader.Instaloader(
            download_pictures=True,
            download_geotags=True, 
            download_videos=False, 
            download_video_thumbnails=False, 
            download_comments=False,
            save_metadata=True,
            compress_json=False
        )
        self.username = username
        self.password = password
        self.dirname = dirname
        self.hashtag = hashtag
        self.numrows = numrows

    def __del__(self):
        self._stop_process()

    def _stop_process(self):
        print('killing process')
        pid = os.getpid()
        os.kill(pid, signal.SIGTERM)
        print('killed process:', pid)

    def run(self):
        self._load_posts()

    def _load_posts(self):
        print("spawned process:", os.getpid())
        try:
            self.loader.login(self.username, self.password)
        except Exception as ex:
            print('could not login successfully.')
            print(ex)
        else:
            print('logged in successfully')

        if self.hashtag[0] == '#':
            self.hashtag = self.hashtag[1:]


        postCount = 0
        hashtagObj = Hashtag.from_name(self.loader.context, self.hashtag)

        for post in hashtagObj.get_posts_resumable():
            try:
                self.loader.download_post(post, target=Path(self.dirname))
                postCount += 1
            except:
                print(f"could not download {post.shortcode}")
            if postCount > 0:
                break

        print("downloaded", postCount, "posts")
        self._process_posts()
        self._stop_process()

    def _process_data_file(self, json_file):
        post = load_structure_from_file(self.loader.context, json_file)
        filename, extension = os.path.splitext(json_file)
        captionFileName = filename + ".txt"

        if os.path.isfile(captionFileName):
            try:
                with open(captionFileName, 'r', encoding='utf-8') as captionFile:
                    caption = captionFile.read()
                # print("read caption from caption file", captionFileName)
            except Exception as ex:
                # print('failed to read from caption file', captionFileName)
                # print(ex)
                caption = post.caption
        else:
            # print(captionFileName, 'does not exist')
            caption = post.caption

        return {
            "title": post.title,
            "username": post.owner_username,
            "date": post.date_local,
            "location": post.location,
            "caption": caption,
            "hashtags": post.caption_hashtags
        }

    def _process_posts(self):
        json_files = [os.path.join(self.dirname, json_file) for json_file in os.listdir(self.dirname) if json_file.endswith('.json')]

        # json_comment_files = [json_file for json_file in json_files if json_file.endswith('_comments.json')]
        json_data_files = [json_file for json_file in json_files if not json_file.endswith('_comments.json')]

        csvFile = open(os.path.join(self.dirname, f"{self.hashtag}.csv"), 'w', encoding='utf-8')
        csvWrite = csv.writer(csvFile, lineterminator='\n')

        csvWrite.writerow(["id", "username", "caption", "hashtags", "date", "lat", "lng", "location"])

        for index, json_data_file in enumerate(json_data_files):
            data = self._process_data_file(json_data_file)
            loc = data['location']
            if loc != None:
                if type(loc.lat) == tuple:
                    lat = loc.lat[0]
                else:
                    lat = loc.lat,
                if type(loc.lng) == tuple:
                    lng = loc.lng[0]
                else:
                    lng = loc.lng
                location = loc.name
            else:
                lat, lng, location = '', '', ''

            row = [
                index+1, 
                data['username'], 
                data['caption'], 
                " ".join([f"#{hashtag}" for hashtag in data['hashtags']]),
                data['date'].strftime('%Y-%m-%d'), 
                str(lat) if lat is not None else '', 
                str(lng) if lng is not None else '',
                location if location is not None else ''
            ]

            csvWrite.writerow(row)

        csvFile.close()
        print('flushed data to csv file')
"""



if __name__ == "__main__":
    app = QApplication([])
    
    # store in logfile
    logfile = os.path.join(os.path.dirname(__file__), ".log")
    sys.stdout = open(logfile, 'w')

    gui = InstaDialog()
    gui.show()
    sys.exit(app.exec_())

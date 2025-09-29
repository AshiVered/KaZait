# -*- coding: utf-8 -*-

import wx
import wx.adv
import os
import sys
import subprocess
import time
import datetime
import tempfile
import ctypes.wintypes
import re
import string
import urllib.parse
import threading
from queue import Queue, Empty
import webbrowser
import json

# --- Helper Functions ---

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def load_strings():
    """Loads UI strings from a JSON file."""
    try:
        with open(resource_path('strings.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Fallback for graceful failure if JSON is missing
        print("Error: strings.json not found!")
        return {}

# Load strings at startup
S = load_strings()
APP_VERSION = "0.5" # Manual version, since updater is removed

def get_win_my_documents():
    """Gets the 'My Documents' folder path on Windows."""
    if os.name != 'nt':
        return os.path.expanduser("~")
    try:
        CSIDL_PERSONAL = 5
        SHGFP_TYPE_CURRENT = 0
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        return buf.value if os.path.isdir(buf.value) else os.path.expanduser("~")
    except Exception:
        return os.path.expanduser("~")

# --- Drag and Drop Target ---

class FileDropTarget(wx.FileDropTarget):
    """Enables Drag and Drop functionality for files."""
    def __init__(self, window):
        super(FileDropTarget, self).__init__()
        self.window = window

    def OnDropFiles(self, x, y, filenames):
        if filenames:
            # Handle the first dropped file
            path = filenames[0]
            if os.path.isfile(path):
                self.window.set_file_name(path)
                return True
        return False

# --- Progress Dialog ---

class ProgressDialog(wx.Dialog):
    """A dialog to show the progress of the ffmpeg conversion."""
    def __init__(self, parent):
        super(ProgressDialog, self).__init__(parent, title=S.get("progress_window_title", "Working..."), style=wx.DEFAULT_DIALOG_STYLE)
        
        self.gauge = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL | wx.GA_TEXT)
        
        grid = wx.GridSizer(rows=3, cols=3, vgap=5, hgap=5)
        
        self.elapsed_time = wx.StaticText(self, label="0")
        self.remaining_time = wx.StaticText(self, label="0")
        self.total_time = wx.StaticText(self, label="0")

        grid.Add(wx.StaticText(self, label=S.get("progress_elapsed", "Elapsed")), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.elapsed_time, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(self, label=S.get("progress_seconds", "seconds")), 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(wx.StaticText(self, label=S.get("progress_remaining", "Remaining")), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.remaining_time, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(self, label=S.get("progress_seconds", "seconds")), 0, wx.ALIGN_CENTER_VERTICAL)

        grid.Add(wx.StaticText(self, label=S.get("progress_total", "Total")), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.total_time, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(wx.StaticText(self, label=S.get("progress_seconds", "seconds")), 0, wx.ALIGN_CENTER_VERTICAL)
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        self.SetSizerAndFit(vbox)

    def update(self, percentage, elapsed, remaining, total):
        self.gauge.SetValue(percentage)
        self.elapsed_time.SetLabel(str(int(elapsed)))
        self.remaining_time.SetLabel(str(int(remaining)))
        self.total_time.SetLabel(str(int(total)))


# --- Main Application Frame ---

class MainFrame(wx.Frame):
    """Main application window."""
    qualities = {
        1: '8k', 2: '16k', 3: '24k', 4: '32k', 5: '40k',
        6: '48k', 7: '64k', 8: '80k', 9: '96k', 10: '112k',
    }
    default_quality = 3

    def __init__(self):
        super(MainFrame, self).__init__(None, title=S.get("window_title", "KaZait"), style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
        
        self.orig_file_name = None
        self.new_file_name = None
        self.proc = None
        self.progress_dialog = ProgressDialog(self)

        self.panel = wx.Panel(self)
        self.SetDropTarget(FileDropTarget(self))
        self.panel.SetDropTarget(FileDropTarget(self))

        self._create_menu()
        self._create_ui()
        
        self.SetMinSize(self.GetSize())
        self.Center()
        self.Show()

    def _create_menu(self):
        menu_bar = wx.MenuBar()
        
        # File Menu
        file_menu = wx.Menu()
        self.do_compress_item = file_menu.Append(wx.ID_ANY, S.get("do_compress_menu", "Compress"))
        self.do_compress_item.Enable(False)
        file_menu.AppendSeparator()
        quit_item = file_menu.Append(wx.ID_EXIT, S.get("quit_menu", "Quit"))
        menu_bar.Append(file_menu, S.get("file_menu", "&File"))
        
        # Help Menu
        help_menu = wx.Menu()
        info_item = help_menu.Append(wx.ID_HELP, S.get("info_menu", "Info"))
        bug_item = help_menu.Append(wx.ID_ANY, S.get("report_bug_menu", "Report Bug"))
        about_item = help_menu.Append(wx.ID_ABOUT, S.get("about_menu", "About"))
        menu_bar.Append(help_menu, S.get("help_menu", "&Help"))

        self.SetMenuBar(menu_bar)

        # Bind events
        self.Bind(wx.EVT_MENU, self.on_start_action, self.do_compress_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), quit_item)
        self.Bind(wx.EVT_MENU, self.on_info, info_item)
        self.Bind(wx.EVT_MENU, self.on_bug_report, bug_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

    def _create_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # --- File Chooser ---
        file_sizer = wx.BoxSizer(wx.HORIZONTAL)
        file_label = wx.StaticText(self.panel, label=S.get("select_file_label", "Select or drag an audio file:"))
        
        sound_wildcard = ";".join([
            "*.wav", "*.mp3", "*.wma", "*.amr", "*.3gp"
        ])
        
        self.file_picker = wx.FilePickerCtrl(self.panel, message=S.get("select_file_button", "Select File"),
                                             wildcard=f"{S.get('file_filter_sound', 'Sound Files')}|{sound_wildcard}|{S.get('file_filter_all', 'All Files')}|*.*")
        
        file_sizer.Add(file_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        # --- THIS IS THE CORRECTED LINE ---
        file_sizer.Add(self.file_picker, 1, wx.EXPAND)
        # ----------------------------------
        main_sizer.Add(file_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # --- Quality Slider ---
        quality_box = wx.StaticBox(self.panel, label=S.get("quality_frame_label", "File Quality"))
        quality_sizer = wx.StaticBoxSizer(quality_box, wx.VERTICAL)
        
        slider_labels_sizer = wx.BoxSizer(wx.HORIZONTAL)
        slider_labels_sizer.Add(wx.StaticText(self.panel, label=S.get("quality_low", "Lowest")), 0)
        slider_labels_sizer.Add((0, 0), 1, wx.EXPAND)
        self.default_quality_button = wx.Button(self.panel, label=S.get("quality_default_button", "Set Recommended Quality"))
        self.default_quality_button.Enable(False)
        slider_labels_sizer.Add(self.default_quality_button, 0, wx.ALIGN_CENTER)
        slider_labels_sizer.Add((0, 0), 1, wx.EXPAND)
        slider_labels_sizer.Add(wx.StaticText(self.panel, label=S.get("quality_high", "Highest")), 0)
        
        self.quality_slider = wx.Slider(self.panel, value=self.default_quality, minValue=1, maxValue=10, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        
        quality_sizer.Add(slider_labels_sizer, 0, wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 5)
        quality_sizer.Add(self.quality_slider, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(quality_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # --- Output and OK button ---
        output_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.output_label = wx.StaticText(self.panel, label="")
        self.ok_button = wx.Button(self.panel, label=S.get("ok_button", "OK"))
        self.ok_button.Enable(False)
        
        output_sizer.Add(self.output_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        output_sizer.Add(self.ok_button, 0, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(output_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        # --- Status Bar ---
        self.CreateStatusBar()
        self.SetStatusText(S.get("statusbar_initial", "Welcome!"))
        
        # Bind events
        self.file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self.on_file_set)
        self.default_quality_button.Bind(wx.EVT_BUTTON, self.on_back_to_default_quality)
        self.quality_slider.Bind(wx.EVT_SLIDER, self.on_slider_change)
        self.ok_button.Bind(wx.EVT_BUTTON, self.on_start_action)

        self.panel.SetSizerAndFit(main_sizer)
        self.Fit()
        
    def set_file_name(self, path):
        """Sets the input filename and determines the output filename."""
        self.orig_file_name = path
        self.file_picker.SetPath(path)
        
        base_name, _ = os.path.splitext(self.orig_file_name)
        self.new_file_name = base_name + ".mp3"
        
        i = 0
        while os.path.exists(self.new_file_name):
            i += 1
            self.new_file_name = f"{base_name}_{i}.mp3"
        
        self.output_label.SetLabel(os.path.basename(self.new_file_name))
        self.set_oks_sensitivities(True)

    def set_oks_sensitivities(self, enabled):
        """Enable or disable action buttons."""
        self.ok_button.Enable(enabled)
        self.do_compress_item.Enable(enabled)

    def on_file_set(self, event):
        self.set_file_name(event.GetPath())

    def on_back_to_default_quality(self, event):
        self.quality_slider.SetValue(self.default_quality)
        self.default_quality_button.Enable(False)
        
    def on_slider_change(self, event):
        is_default = self.quality_slider.GetValue() == self.default_quality
        self.default_quality_button.Enable(not is_default)

    def on_start_action(self, event):
        """Starts the ffmpeg conversion process in a separate thread."""
        self.set_oks_sensitivities(False)
        self.SetStatusText(S.get("statusbar_working", "Working, please wait..."))

        thread = threading.Thread(target=self._run_ffmpeg_thread)
        thread.daemon = True
        thread.start()

        self.progress_dialog.ShowModal()

    def _run_ffmpeg_thread(self):
        """The core ffmpeg execution logic that runs in a background thread."""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        quality = self.qualities[self.quality_slider.GetValue()]
        progress_file = tempfile.NamedTemporaryFile(delete=False).name

        command = [
            resource_path('ffmpeg.exe'),
            '-i', self.orig_file_name,
            '-b:a', quality,
            '-progress', progress_file,
            '-nostats',
            '-y', # Overwrite output file
            self.new_file_name
        ]
        
        try:
            self.proc = subprocess.Popen(
                command,
                startupinfo=startupinfo,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            # --- Progress Monitoring ---
            duration = self._get_duration_from_ffmpeg()
            self._monitor_progress(progress_file, duration)
            
            self.proc.wait() # Wait for process to finish
            
        finally:
            if os.path.exists(progress_file):
                os.remove(progress_file)
            
            wx.CallAfter(self.finish_action)
            
    def _get_duration_from_ffmpeg(self):
        """Reads ffmpeg's stderr to find the media duration."""
        duration = 0
        duration_re = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})")
        
        while True:
            line = self.proc.stderr.readline()
            if not line:
                break
            match = duration_re.search(line)
            if match:
                h, m, s, _ = map(int, match.groups())
                duration = h * 3600 + m * 60 + s
                # Now that we have the duration, we can start monitoring
                return duration
        return duration # Fallback

    def _monitor_progress(self, progress_file, duration):
        """Monitors the progress file and updates the progress dialog."""
        start_time = time.time()
        last_pos = 0
        
        while self.proc.poll() is None:
            time.sleep(0.1) # Avoid busy-waiting
            
            out_time_s = 0
            try:
                with open(progress_file, 'r') as f:
                    f.seek(last_pos)
                    for line in f:
                        if "out_time_ms" in line:
                           out_time_s = int(line.strip().split('=')[1]) / 1_000_000
                    last_pos = f.tell()
            except FileNotFoundError:
                continue # File might not be created yet

            if duration > 0 and out_time_s > 0:
                done_part = out_time_s / duration
                percentage = min(100, int(done_part * 100))
                
                elapsed = time.time() - start_time
                total_time = (elapsed / done_part) if done_part > 0 else 0
                remaining = max(0, total_time - elapsed)

                wx.CallAfter(self.progress_dialog.update, percentage, elapsed, remaining, total_time)

    def finish_action(self):
        """Called on the main thread after ffmpeg finishes."""
        self.progress_dialog.Hide()
        self.set_oks_sensitivities(True)
        self.SetStatusText(S.get("statusbar_initial", "Welcome!"))

        if self.proc and self.proc.returncode == 0:
            wx.MessageBox(S.get("finish_success_message", "File %s is ready.") % self.new_file_name,
                          S.get("finish_success_title", "Success"), wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(S.get("finish_fail_message", "Failed to process %s.") % self.orig_file_name,
                          S.get("finish_fail_title", "Error"), wx.OK | wx.ICON_ERROR)

        # Prepare for next run
        if self.orig_file_name:
            self.set_file_name(self.orig_file_name)

    # --- Menu Handlers ---

    def on_info(self, event):
        try:
            with open(resource_path('explainDialog.txt'), 'r', encoding='utf-8') as f:
                info_text = f.read()
        except FileNotFoundError:
            info_text = "explainDialog.txt not found."
            
        wx.MessageBox(info_text, S.get("info_dialog_title", "Information"), wx.OK | wx.ICON_INFORMATION)
        
    def on_bug_report(self, event):
        subject = S.get("bug_report_subject", "KaZait Bug Report")
        webbrowser.open(f"https://github.com/ZvikaZ/KaZait/issues/new")

    def on_about(self, event):
        info = wx.adv.AboutDialogInfo()
        info.SetName(S.get("about_dialog_name", "KaZait"))
        info.SetVersion(APP_VERSION)
        info.SetDescription(S.get("about_dialog_version_prefix", "Version ") + APP_VERSION)
        info.SetCopyright(S.get("about_dialog_copyright", "(C) 2024 Zvika Haramaty"))
        info.SetWebSite(S.get("about_dialog_website", ""), "Project Homepage")
        
        wx.adv.AboutBox(info)

if __name__ == "__main__":
    app = wx.App(False)
    frame = MainFrame()
    app.MainLoop()
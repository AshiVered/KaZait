# תוכנת שיעור כזית

תוכנה לכיווץ נפח קבצי שמע, מבוססת על FFMPEG.
פותחה במקור על ידי צביקה הרמתי, עודכנה לפייתון 3 וממשק מודרני על ידי אשי ורד.


# תלויות

wxPython - התקנה מpip
    
pip install wxpython

ffpeg - יש למקם קובץ exe בתיקיה.

# קימפול

pyinstaller --onefile --windowed --add-data "strings.json;." --add-data "explainDialog.txt;." --add-data "ffmpeg.exe;." KaZait_wx.py

### הערה קטנה

אני יודע שמקובל בפייתון לשלב את הסטרינגים ישירות בקוד ולא בקובץ strings.json נפרד, אך אני מפתח אנדרואיד בעיקר והיה לי יותר נוח למקם את הסטרינגים בקובץ נפרד, כמקובל באנדרואיד :)
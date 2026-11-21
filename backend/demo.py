from .models import Lesson

ROAD = {"title":"Cơ học nhập môn","goal":"Hiểu và kiểm chứng các quy luật chuyển động.",
        "chapters":[{"title":"Chuyển động thẳng","topics":[
            {"id":"roi-tu-do","title":"Sự rơi tự do","goal":"Giải thích quan hệ giữa thời gian và quãng đường rơi."},
            {"id":"gia-toc","title":"Vận tốc và gia tốc","goal":"Phân biệt vận tốc, gia tốc và đọc đồ thị vận tốc."}]}]}

SAMPLE = Lesson.model_validate({
    "intro":"Nếu thời gian rơi tăng gấp đôi, một vật sẽ đi được quãng đường gấp mấy lần?",
    "sections":[{"title":"Vật rơi nhanh dần như thế nào?","text":"Hãy hình dung bạn thả một viên bi từ trạng thái nghỉ. Bỏ qua sức cản không khí và chọn chiều dương hướng xuống. Gần mặt đất, sau mỗi giây vận tốc của viên bi tăng thêm khoảng 9,81 m/s.\n\nVận tốc tăng đều, nhưng quãng đường đi được trong mỗi giây lại dài hơn giây trước. Hãy thử dự đoán vị trí của viên bi sau hai giây."},
                {"title":"Từ đồ thị đến công thức","text":"Vận tốc trung bình khi rơi từ trạng thái nghỉ là gt/2. Nhân với thời gian, ta có s = ½gt².\n\nVới g = 9,81 m/s² và t = 2 s, quãng đường rơi là ½ × 9,81 × 2² = 19,62 m. Tăng gấp đôi thời gian làm quãng đường tăng gấp bốn lần."}],
    "illustrations":[{"section":0,"title":"Phòng thí nghiệm rơi tự do","instruction":"Dự đoán vị trí của viên bi, rồi kéo thời gian từ 1 đến 2 giây. So sánh khoảng cách giữa các vạch từng giây.","explanation":"Ở cùng gia tốc và vận tốc đầu bằng 0, quãng đường tỉ lệ với bình phương thời gian. Các vạch ghi vị trí sau từng giây cách nhau ngày càng xa.","mode":"motion",
        "html":'<svg viewBox="0 0 160 230"><line x1="48" x2="48" y1="16" y2="216" stroke="#79998b"/><circle id="ball" cx="48" cy="16" r="9" fill="#b95224"/><text id="read" x="65" y="26" fill="#21493d"></text></svg>',
        "css":"svg { width: 100%; }","js":"function render(t,s,v,k){var y=16+200*k/100;attr('ball','cy',y);attr('read','y',Math.min(216,y+4));text('read',s.toFixed(2)+' m');}"}],
    "quiz":[{"kind":"number","prompt":"Thả vật từ trạng thái nghỉ trong 2 giây với g = 9,81 m/s². Vật rơi được bao xa?","choices":[],"answer":"19.62 m","explanation":"s = ½ × 9,81 × 2² = 19,62 m, cũng bằng 1962 cm."},
            {"kind":"choice","prompt":"Sau 3 giây, quãng đường gấp mấy lần quãng đường sau 1 giây?","choices":["3 lần","6 lần","9 lần"],"answer":"9 lần","explanation":"Tỉ số quãng đường bằng (3/1)² = 9."}]
}).model_dump()


ROAD_EN = {
    "title": "Introduction to mechanics",
    "goal": "Understand and test the laws of motion.",
    "chapters": [{"title": "Motion in a straight line", "topics": [
        {"id": "free-fall", "title": "Free fall", "goal": "Explain how the distance fallen depends on time."},
        {"id": "acceleration", "title": "Velocity and acceleration", "goal": "Distinguish velocity from acceleration and read a velocity graph."},
    ]}],
}

SAMPLE_EN = Lesson.model_validate({
    "intro": "If you double the time an object falls, how much farther does it travel?",
    "sections": [
        {"title": "How fast does a falling object speed up?",
         "text": "Imagine dropping a marble from rest. Ignore air resistance and take downward as positive. Near the ground, the marble gains about 9.81 m/s of velocity each second.\n\nIts velocity increases steadily, but it travels farther each second than it did the second before. Where do you think it will be after two seconds?"},
        {"title": "From the graph to the equation",
         "text": "For an object falling from rest, the average velocity is gt/2. Multiply by time to get the distance fallen, s = ½gt².\n\nWith g = 9.81 m/s² and t = 2 s, the marble falls ½ × 9.81 × 2² = 19.62 m. Doubling the time quadruples the distance."},
    ],
    "illustrations": [{
        **SAMPLE["illustrations"][0],
        "title": "Free-fall lab",
        "instruction": "Predict the marble’s position, then move the time slider from 1 to 2 seconds. Compare the gaps between the one-second marks.",
        "explanation": "With constant acceleration and zero initial velocity, the distance fallen is proportional to time squared. The marks showing the position at each second get farther apart.",
    }],
    "quiz": [
        {"kind": "number", "prompt": "An object falls from rest for 2 seconds with g = 9.81 m/s². How far does it fall?", "choices": [], "answer": "19.62 m", "explanation": "s = ½ × 9.81 × 2² = 19.62 m, or 1962 cm."},
        {"kind": "choice", "prompt": "How far does the object fall in 3 seconds compared with 1 second?", "choices": ["3 times as far", "6 times as far", "9 times as far"], "answer": "9 times as far", "explanation": "The ratio of the distances is (3/1)² = 9."},
    ],
}).model_dump()

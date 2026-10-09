"""Công cụ cho thí sinh/BTC gửi bài mà không cần curl.
  python client.py register TEN          -> đăng ký, lưu token vào token_TEN.txt
  python client.py submit TEN bot.py     -> nộp bài
  python client.py me TEN                -> xem trạng thái
  python client.py board TEN             -> xem BXH bảng của mình
Đổi địa chỉ server bằng biến môi trường OTT_URL (mặc định http://localhost:8000)."""
import sys, os, json, uuid, urllib.request, urllib.error

URL = os.environ.get("OTT_URL", "http://localhost:8000")


def call(path, token=None, body=None, ctype=None):
    h = {"X-Token": token} if token else {}
    if ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(URL + path, data=body, headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def tok(name):
    with open(f"token_{name}.txt") as f:
        return f.read().strip()


def main():
    cmd, name = sys.argv[1], sys.argv[2]
    if cmd == "register":
        r = call("/register", body=json.dumps({"name": name}).encode(), ctype="application/json")
        if "token" in r:
            open(f"token_{name}.txt", "w").write(r["token"])
            print("Dang ky thanh cong. Token luu trong token_%s.txt (giu kin)" % name)
        else:
            print(r)
    elif cmd == "submit":
        data = open(sys.argv[3], "rb").read()
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="bot.py"\r\n'
                f'Content-Type: text/x-python\r\n\r\n').encode() + data + f"\r\n--{b}--\r\n".encode()
        print(call("/submit", tok(name), body, f"multipart/form-data; boundary={b}"))
    elif cmd == "me":
        print(json.dumps(call("/me", tok(name)), indent=1, ensure_ascii=False))
    elif cmd == "board":
        for row in call("/leaderboard", tok(name)):
            print(row)


main()

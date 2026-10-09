# Chạy server nhận bài bằng waitress (dùng được trên Windows). Gọi: python serve.py
import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))   # luôn chạy trong thư mục ott
sys.path.insert(0, os.getcwd())
from waitress import serve
import server
print("Server dang chay tai http://localhost:8000  (dong cua so nay de tat)")
serve(server.app, host="0.0.0.0", port=8000)

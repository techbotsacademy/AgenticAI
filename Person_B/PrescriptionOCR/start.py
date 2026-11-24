
import http.server
import socketserver
import webbrowser
import os

PORT = 8001
HOST = "127.0.0.1"

# Directory containing your HTML files
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
os.chdir(DIRECTORY)

Handler = http.server.SimpleHTTPRequestHandler

try:
    with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}"

        print(f"Server running at: {url}")
        print("Press Ctrl+C to stop the server.")

        webbrowser.open(url)

        httpd.serve_forever()

except OSError as e:
    print(f"Unable to start server: {e}")

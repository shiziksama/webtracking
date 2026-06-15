Build the entire project from scratch. Optimize for simplicity, not scalability.
Create a complete Dockerized pet project for browser-based object tracking.

Goal:
A user opens a website from a phone, allows camera access, sees live camera video, selects an object by dragging a rectangle over the video, and the backend tracks that object using OpenCV. The backend returns bounding boxes in real time and the frontend draws them over the video.

The entire project must run with:

```bash
docker compose up -d
```

No additional manual steps should be required except setting an ngrok auth token.

---

Tech stack:

Backend:

* Python 3.11
* FastAPI
* WebSocket
* OpenCV (opencv-contrib-python)
* NumPy
* Uvicorn

Frontend:

* Vite + TypeScript
* HTML5 video
* Canvas overlay

Infrastructure:

* Docker
* Docker Compose
* ngrok container

---

Requirements

1. Frontend

* Access camera via getUserMedia().
* Show live video.
* Allow selecting an object by dragging a rectangle.
* Send JPEG frames to backend via WebSocket.
* Receive bbox updates.
* Draw bbox overlay.
* Show tracking state:

  * idle
  * tracking
  * lost

---

2. Backend

Provide:

GET /
GET /api/info
WebSocket /ws/track

The API should expose:

```json
{
  "local_url": "http://localhost:8000",
  "public_url": "https://xxxxx.ngrok-free.app",
  "websocket_url": "wss://xxxxx.ngrok-free.app/ws/track"
}
```

The frontend must automatically fetch and display this information.

---

3. Tracking

Use OpenCV CSRT tracker.

Workflow:

* User selects rectangle.
* Backend initializes tracker.
* Each new frame updates tracker.
* Return:

```json
{
  "type": "bbox",
  "bbox": {
    "x": 10,
    "y": 20,
    "w": 100,
    "h": 50
  },
  "ok": true
}
```

or

```json
{
  "type": "lost",
  "ok": false
}
```

---

4. Docker

Provide:

Dockerfile
docker-compose.yml
.env.example

Project should start with:

```bash
docker compose up -d
```

Services:

* frontend
* backend
* ngrok

The frontend and backend must communicate through Docker networking.

---

5. Ngrok integration

Use official ngrok container.

Environment variables:

```env
NGROK_AUTHTOKEN=
```

Expose backend through ngrok.

The backend must automatically discover the ngrok public URL using the ngrok API:

```
http://ngrok:4040/api/tunnels
```

Store the discovered public URL in memory and expose it through:

```
GET /api/info
```

---

6. Startup page

Homepage should display:

* Local URL
* Public ngrok URL
* WebSocket URL
* Backend status
* Tracker status

Example:

Backend: Online
Ngrok: Connected

Local:
http://localhost:8000

Public:
https://xxxxx.ngrok-free.app

WebSocket:
wss://xxxxx.ngrok-free.app/ws/track

````

Include a button:

```text
Open Camera
````

---

7. Code quality

* Keep architecture simple.
* Use typed TypeScript.
* Use async FastAPI handlers.
* Add comments explaining:

  * camera pipeline
  * websocket pipeline
  * tracking lifecycle

---

8. README

Include:

* setup
* docker compose usage
* ngrok token configuration
* architecture diagram
* troubleshooting
* known limitations

---

Future roadmap section:

* WebRTC instead of JPEG over WebSocket
* YOLO object detection
* Segment Anything integration
* Multi-object tracking
* GPU acceleration
* Recording tracked sessions



Use the simplest implementation possible.
Do not over-engineer.
Do not add authentication.
Do not add database.
Do not add tests.
Do not add CI/CD.
Do not add production deployment.



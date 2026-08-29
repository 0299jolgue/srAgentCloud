import os
from flask import Flask
from config import BASE_DIR
from database import init_db
from routes import register_routes

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))

init_db()
register_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False, threaded=True)

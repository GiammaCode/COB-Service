import os
import socket
from flask import Flask, send_from_directory
from flask_cors import CORS
from .services import mongodb
from .routes import assignments
from .routes import submissions

def create_app():
    """
    Flask app factory, create application
    """
    app = Flask(__name__)
    CORS(app)

    mongo_uri = os.environ.get('MONGO_URI')
    try:
        mongodb.init_db(mongo_uri)
        print("MongoDB connected with successfully")
    except Exception as e:
        print(f"MongoDB connection error: {e}")

    app.register_blueprint(assignments.assignments_bp)
    app.register_blueprint(submissions.submissions_bp)

    @app.route('/')
    def base_endpoint():
        """Base endpoint for testing purposes (DB connection)) ."""
        db_status = mongodb.check_db_connection()
        container_id =socket.gethostname()

        return {
            "message": "Flask server is alive.",
            "database_status": db_status,
            "container_id": container_id
        }

    return app
from flask import Blueprint, jsonify
from ..services import mongodb
from bson import ObjectId

submissions_bp = Blueprint('submissions_bp', __name__, url_prefix='/submissions')

@submissions_bp.before_request
def check_db_connection():
    if mongodb.submissions_collection is None:
        return jsonify({"error": "Database not connected"}), 500

@submissions_bp.route('', methods=['GET'])
def get_all_submissions():
    """Retrieve all submissions"""
    try:
        submissions = list(mongodb.submissions_collection.find())
        for sub in submissions:
            sub['_id'] = str(sub['_id'])

        return jsonify(submissions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@submissions_bp.route('/<submission_id>', methods=['GET'])
def get_submission(submission_id):
    """Retrieve details of a specific submission"""
    try:
        if not ObjectId.is_valid(submission_id):
            return jsonify({"error": "Submission ID not valid"}), 400

        submission = mongodb.submissions_collection.find_one({"_id": ObjectId(submission_id)})

        if not submission:
            return jsonify({"error": "Submission not found"}), 404

        submission['_id'] = str(submission['_id'])

        return jsonify(submission)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
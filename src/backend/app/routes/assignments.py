import datetime
from flask import Blueprint, request, Response, jsonify
from ..services import mongodb
from bson import ObjectId

assignments_bp = Blueprint('assignments_bp', __name__, url_prefix='/assignments')

@assignments_bp.before_request
def check_db_connection():
    if mongodb.assignments_collection is None or mongodb.submissions_collection is None:
        return jsonify({"error": "Database not connected"}), 500
    return None

@assignments_bp.route('', methods=['POST'])
def create_assignment():
    """Creates a new assignment"""
    data = request.json
    if not data or 'title' not in data:
        return jsonify({"error": "Title missing"}), 400

    new_assignment = {
        "title": data.get('title'),
        "description": data.get('description', ''),
        "due_date": data.get('due_date'),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    }

    result = mongodb.assignments_collection.insert_one(new_assignment)
    new_assignment['_id'] = str(result.inserted_id)

    return jsonify(new_assignment), 201


@assignments_bp.route('', methods=['GET'])
def get_all_assignments():
    """Retrieves all existing assignments"""
    try:
        assignments = list(mongodb.assignments_collection.find({}))
        for assignment in assignments:
            assignment['_id'] = str(assignment['_id'])

        return jsonify(assignments)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@assignments_bp.route('/<assignment_id>', methods=['GET'])
def get_assignment_by_id(assignment_id):
    """Return a single assignment by its ID"""
    try:
        if not ObjectId.is_valid(assignment_id):
            return jsonify({"error": "ID assignment not valid"}), 400

        assignment = mongodb.assignments_collection.find_one({"_id": ObjectId(assignment_id)})
        if not assignment:
            return jsonify({"error": "Assignment not found"}), 404

        assignment['_id'] = str(assignment['_id'])
        return jsonify(assignment)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@assignments_bp.route('/<assignment_id>/submit', methods=['POST'])
def create_submission(assignment_id):
    """ Creates a new submission"""
    try:
        if not ObjectId.is_valid(assignment_id):
            return jsonify({"error": "ID assignment non valido nell'URL"}), 400

        if mongodb.assignments_collection.count_documents({"_id": ObjectId(assignment_id)}) == 0:
            return jsonify({"error": "Assignment not found"}), 404

        data = request.json
        if not data or 'student_name' not in data or 'result' not in data:
            return jsonify({"error": "Missing data"}), 400

        new_submission = {
            "idAssignment": assignment_id,
            "student_name": data['student_name'],
            "submitted_at": datetime.datetime.now(datetime.timezone.utc),
            "result": data['result']
        }

        result = mongodb.submissions_collection.insert_one(new_submission)
        new_submission['_id'] = str(result.inserted_id)
        new_submission['idSubmission'] = str(result.inserted_id)
        return jsonify(new_submission), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
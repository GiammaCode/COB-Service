from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

#global variables
client = None
db = None
assignments_collection = None
submissions_collection = None


def init_db(mongo_uri):
    """
    Initializes the database and attach the collections
    """
    global client, db, assignments_collection, submissions_collection

    if not mongo_uri:
        print("Error: mongo_uri not setted")
        raise ValueError("MONGO_URI not setted")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    #try to ping
    client.admin.command('ping')

    db = client.homework_db
    assignments_collection = db.assignments
    submissions_collection = db.submissions


def check_db_connection():
    """
    Checks the database connection
    """
    if client is None:
        return "Not connected, client not initialized"
    try:
        client.admin.command('ping')
        return "Connected"
    except Exception:
        return "Connection lost"
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5001";

function StudentArea() {
  const [assignments, setAssignments] = useState([]);
  const [selectedAssignment, setSelectedAssignment] = useState(null);
  const [formData, setFormData] = useState({ student_name: '', result: '' });
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetchAssignments();
  }, []);

  const fetchAssignments = async () => {
    try {
      const res = await axios.get(`${API_BASE}/assignments`);
      setAssignments(res.data);
    } catch (error) {
      console.error("Error fetching assignments", error);
    }
  };

  const handleOpenSubmit = (assignment) => {
    setSelectedAssignment(assignment);
    setMessage('');
    setFormData({ student_name: '', result: '' });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedAssignment) return;

    // --- FIX ID LOGIC ---
    let assignmentId = selectedAssignment._id;
    if (typeof assignmentId === 'object' && assignmentId !== null && assignmentId.$oid) {
        assignmentId = assignmentId.$oid;
    }
    // --------------------

    try {
      await axios.post(`${API_BASE}/assignments/${assignmentId}/submit`, formData);
      setMessage('Submission successful!');
      setTimeout(() => {
        setSelectedAssignment(null);
        setMessage('');
      }, 2000);
    } catch (error) {
      console.error("Submission error:", error);
      setMessage('Error: ' + (error.response?.data?.error || error.message));
    }
  };

  return (
    <div className="page-container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Student Area</h2>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>

      <p>Available Assignments:</p>

      <div className="assignments-list">
        {assignments.length === 0 ? <p>No assignments available at the moment.</p> : assignments.map(ass => (
          <div key={ass._id} className="card">
            <h3>{ass.title}</h3>
            <p>{ass.description}</p>
            <small>Due Date: {ass.due_date || 'No deadline'}</small>
            <button onClick={() => handleOpenSubmit(ass)} className="btn btn-primary">
              Submit Work
            </button>
          </div>
        ))}
      </div>

      {/* Submission Modal */}
      {selectedAssignment && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>Submit: {selectedAssignment.title}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Full Name:</label>
                <input
                  type="text"
                  required
                  placeholder="John Doe"
                  value={formData.student_name}
                  onChange={e => setFormData({...formData, student_name: e.target.value})}
                />
              </div>
              <div className="form-group">
                <label>Result / Answer:</label>
                <textarea
                  required
                  rows="5"
                  placeholder="Type your answer here..."
                  value={formData.result}
                  onChange={e => setFormData({...formData, result: e.target.value})}
                />
              </div>
              <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
                <button type="submit" className="btn btn-primary" style={{flex: 1}}>Send</button>
                <button type="button" className="btn btn-secondary" onClick={() => setSelectedAssignment(null)}>Cancel</button>
              </div>
            </form>
            {message && <p className="msg">{message}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

export default StudentArea;
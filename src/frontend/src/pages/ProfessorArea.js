import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5001";

function ProfessorArea() {
  // State for Creating Assignment
  const [newAssign, setNewAssign] = useState({ title: '', description: '', due_date: '' });
  const [msg, setMsg] = useState('');

  // State for Viewing Submissions
  const [submissions, setSubmissions] = useState([]);

  // Fetch submissions immediately on load
  useEffect(() => {
    fetchSubmissions();
  }, []);

  const fetchSubmissions = async () => {
    try {
      const res = await axios.get(`${API_BASE}/submissions`);
      setSubmissions(res.data);
    } catch (error) {
      console.error("Error fetching submissions:", error);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API_BASE}/assignments`, newAssign);
      setMsg('Assignment created successfully!');
      setNewAssign({ title: '', description: '', due_date: '' });
      // Optional: Refresh submissions or add logic here if needed
    } catch (error) {
      setMsg('Error: ' + error.message);
    }
  };

  return (
    <div className="page-container">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Professor Dashboard</h2>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>

      <div className="professor-grid">

        {/* Left Column: Submissions List */}
        <div className="panel view-section">
          <h3>Received Submissions</h3>
          {submissions.length === 0 ? (
            <p>No submissions received yet.</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="sub-table">
                <thead>
                  <tr>
                    <th>Student</th>
                    <th>Date</th>
                    <th>Result/Link</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map(sub => (
                    <tr key={sub._id}>
                      <td>{sub.student_name}</td>
                      <td>{new Date(sub.submitted_at).toLocaleDateString()} {new Date(sub.submitted_at).toLocaleTimeString()}</td>
                      <td>{sub.result}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Right Column: Create Assignment Form */}
        <div className="panel create-section">
          <h3>Create New Assignment</h3>
          <form onSubmit={handleCreate}>
            <div className="form-group">
              <label>Title:</label>
              <input
                type="text" required
                value={newAssign.title}
                onChange={e => setNewAssign({...newAssign, title: e.target.value})}
                placeholder="Ex: Math Homework 1"
              />
            </div>
            <div className="form-group">
              <label>Description:</label>
              <textarea
                rows="4"
                value={newAssign.description}
                onChange={e => setNewAssign({...newAssign, description: e.target.value})}
                placeholder="Enter details..."
              />
            </div>
            <div className="form-group">
              <label>Due Date:</label>
              <input
                type="date"
                value={newAssign.due_date}
                onChange={e => setNewAssign({...newAssign, due_date: e.target.value})}
              />
            </div>
            <button type="submit" className="btn btn-primary" style={{width: '100%'}}>
              Create Assignment
            </button>
          </form>
          {msg && <p className="msg">{msg}</p>}
        </div>

      </div>
    </div>
  );
}

export default ProfessorArea;
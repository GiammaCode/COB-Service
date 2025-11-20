import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Home from './pages/Home';
import StudentArea from './pages/StudentArea';
import ProfessorArea from './pages/ProfessorArea';
import './App.css';

function App() {
  return (
    <Router>
      <div className="app-container">
        <nav className="navbar">
          <h1>Gestionale Compiti</h1>
        </nav>
        <div className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/student" element={<StudentArea />} />
            <Route path="/professor" element={<ProfessorArea />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
}

export default App;
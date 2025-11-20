import React from 'react';
import { Link } from 'react-router-dom';

function Home() {
  return (
    <div className="home-container">
      <h2>Assignment Manager</h2>

      <div className="button-group">
        <Link to="/professor" className="btn btn-home">
          Professor Area
        </Link>
        <Link to="/student" className="btn btn-home">
          Student Area
        </Link>
      </div>
    </div>
  );
}

export default Home;
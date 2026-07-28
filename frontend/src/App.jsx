import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import SearchForm from './components/SearchForm';
import Login from './components/Login';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('Facebook Groups Extractor (Apify)');
  const [username, setUsername] = useState(localStorage.getItem('username') || '');

  const handleLoginSuccess = (user) => {
    setUsername(user);
  };

  const handleLogout = () => {
    localStorage.removeItem('username');
    setUsername('');
  };

  if (!username) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} onLogout={handleLogout} />
      <main className="main-content">
        <div style={{ display: activeTab === 'Facebook Groups Extractor (Apify)' ? 'block' : 'none' }}>
          <SearchForm />
        </div>
        {activeTab !== 'Facebook Groups Extractor (Apify)' && (
          <div className="placeholder-content">
            <h2>{activeTab}</h2>
            <p>Content for {activeTab} will go here.</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
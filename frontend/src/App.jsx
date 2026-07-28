import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import SearchForm from './components/SearchForm';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('Facebook Groups Extractor (Apify)');

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
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
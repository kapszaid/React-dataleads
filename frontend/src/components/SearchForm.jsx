import React, { useState, useEffect } from 'react';
import './SearchForm.css';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function SearchForm() {
  const [searchType, setSearchType] = useState('scraper_engine');
  const [searchInput, setSearchInput] = useState('');
  const [maxItems, setMaxItems] = useState(20);
  const [searchLoading, setSearchLoading] = useState(false);
  const [enhanceLoading, setEnhanceLoading] = useState(false);
  const [aiSuggestions, setAiSuggestions] = useState([]);
  const [selectedSuggestions, setSelectedSuggestions] = useState(new Set());
  const [searchResults, setSearchResults] = useState(null);
  const [activeTab, setActiveTab] = useState('table');
  const [currentRunId, setCurrentRunId] = useState(null);
  const [searchStatus, setSearchStatus] = useState(null);

  const isEasyApi = searchType === 'easyapi';

  useEffect(() => {
    const fetchLatestRun = async () => {
      try {
        const username = localStorage.getItem('username') || '';
        const response = await fetch(`${API_BASE_URL}/api/search/latest`, {
          headers: {
            'X-User-Username': username
          }
        });
        if (!response.ok) return;
        const data = await response.json();
        setSearchResults(data);
        setSearchType(data.search_type || 'scraper_engine');
        setSearchInput(data.search_input || '');
        setMaxItems(data.max_items || 20);
        setCurrentRunId(data.run_id || null);
        setSearchStatus(data.status || null);
        
        if (data.status === 'RUNNING' && data.run_id) {
          setSearchLoading(true);
        }
      } catch (err) {
        console.error('Failed to load latest search run:', err);
      }
    };
    fetchLatestRun();
  }, []);

  useEffect(() => {
    let intervalId;
    if (searchLoading && currentRunId && searchStatus === 'RUNNING') {
      intervalId = setInterval(async () => {
        try {
          const username = localStorage.getItem('username') || '';
          const response = await fetch(`${API_BASE_URL}/api/search/status/${currentRunId}`, {
            headers: {
              'X-User-Username': username
            }
          });
          if (!response.ok) {
            throw new Error('Failed to fetch status');
          }
          const data = await response.json();
          setSearchStatus(data.status);
          if (data.status !== 'RUNNING') {
            setSearchResults(data);
            setSearchLoading(false);
            clearInterval(intervalId);
          }
        } catch (err) {
          console.error('Error polling status:', err);
        }
      }, 3000);
    }
    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [searchLoading, currentRunId, searchStatus]);

  const parseEntries = (text) => {
    return text
      .replace(/\r/g, '\n')
      .split('\n')
      .reduce((acc, part) => {
        part.split(',').forEach((chunk) => {
          const value = chunk.trim();
          if (value && !acc.includes(value)) {
            acc.push(value);
          }
        });
        return acc;
      }, []);
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchInput.trim()) {
      alert('Error: Search Input cannot be empty.');
      return;
    }
    setSearchLoading(true);
    setSearchResults(null);
    setCurrentRunId(null);
    setSearchStatus(null);
    try {
      const username = localStorage.getItem('username') || '';
      const response = await fetch(`${API_BASE_URL}/api/search/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User-Username': username
        },
        body: JSON.stringify({
          searchType,
          searchInput: searchInput.trim(),
          maxItems: Number(maxItems),
        }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to start search');
      }
      const data = await response.json();
      setCurrentRunId(data.run_id);
      setSearchStatus(data.status);
    } catch (err) {
      console.error(err);
      alert(`Search failed: ${err.message}`);
      setSearchLoading(false);
    }
  };

  const handleStopSearch = async () => {
    if (!currentRunId) return;
    try {
      const username = localStorage.getItem('username') || '';
      const response = await fetch(`${API_BASE_URL}/api/search/stop/${currentRunId}`, {
        method: 'POST',
        headers: {
          'X-User-Username': username
        }
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to stop search');
      }
      setSearchStatus('ABORTED');
      setSearchLoading(false);
      alert('Search run aborted successfully.');
    } catch (err) {
      console.error(err);
      alert(`Failed to stop search: ${err.message}`);
    }
  };

  const handleAiEnhance = async (e) => {
    e.preventDefault();
    if (!searchInput.trim()) {
      alert('Error: Please enter a query first to use AI Enhance.');
      return;
    }
    setEnhanceLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/enhance`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ keyword: searchInput }),
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to enhance keywords');
      }
      const data = await response.json();
      setAiSuggestions(data.suggestions || []);
      setSelectedSuggestions(new Set());
    } catch (err) {
      console.error(err);
      alert(`AI Enhance failed: ${err.message}`);
    } finally {
      setEnhanceLoading(false);
    }
  };

  const handleToggleSuggestion = (suggestion) => {
    const entries = parseEntries(searchInput);
    const isSelected = selectedSuggestions.has(suggestion);
    const newSelected = new Set(selectedSuggestions);
    
    let updatedEntries;
    if (isSelected) {
      newSelected.delete(suggestion);
      updatedEntries = entries.filter((entry) => entry.toLowerCase() !== suggestion.toLowerCase());
    } else {
      newSelected.add(suggestion);
      if (!entries.some(entry => entry.toLowerCase() === suggestion.toLowerCase())) {
        entries.push(suggestion);
      }
      updatedEntries = entries;
    }
    
    setSelectedSuggestions(newSelected);
    setSearchInput(updatedEntries.join(', '));
  };

  const downloadCSV = () => {
    if (!searchResults) return;
    const headers = ['Query', 'Group ID', 'Group Name', 'URL', 'Visibility', 'Members', 'Post Frequency', 'Type', 'Join State'];
    const rows = searchResults.groups.map(g => [
      `"${(g.query || '').replace(/"/g, '""')}"`,
      `"${(g.id || '').replace(/"/g, '""')}"`,
      `"${(g.name || '').replace(/"/g, '""')}"`,
      `"${(g.url || '').replace(/"/g, '""')}"`,
      `"${(g.visibility || '').replace(/"/g, '""')}"`,
      `"${(g.members || '').replace(/"/g, '""')}"`,
      `"${(g.postFrequency || '').replace(/"/g, '""')}"`,
      `"${(g.type || '').replace(/"/g, '""')}"`,
      `"${(g.joinState || '').replace(/"/g, '""')}"`
    ]);
    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', 'facebook_groups.csv');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadJSON = () => {
    if (!searchResults) return;
    const blob = new Blob([JSON.stringify(searchResults.raw_output, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', 'facebook_groups.json');
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const uniqueQueriesCount = searchResults && searchResults.groups
    ? new Set(searchResults.groups.map(g => g.query.trim().toLowerCase()).filter(Boolean)).size
    : 0;

  return (
    <div className="search-form">
      <header className="search-form__header">
        <h1 className="search-form__title">Facebook Groups Extractor (Apify)</h1>
      </header>

      <form className="search-form__body" onSubmit={handleSearch}>
        <div className="search-form__row">
          <div className="search-form__group search-form__group--type">
            <label htmlFor="searchType" className="search-form__label">
              Search Type
            </label>
            <select
              id="searchType"
              className="search-form__select"
              value={searchType}
              onChange={(e) => {
                setSearchType(e.target.value);
                setAiSuggestions([]);
                setSelectedSuggestions(new Set());
              }}
              disabled={searchLoading}
            >
              <option value="scraper_engine">Keyword / Group URL (Scraper Engine)</option>
              <option value="simpleapi">Keyword / Group URL (SimpleAPI)</option>
              <option value="scrapio">Keyword / Group URL (Scrapio)</option>
              <option value="easyapi">Keyword Search (EasyAPI)</option>
            </select>
          </div>

          <div className="search-form__group search-form__group--input">
            <label htmlFor="searchInput" className="search-form__label">
              {isEasyApi ? 'Search Query' : 'Search Input'}
            </label>
            <input
              id="searchInput"
              type="text"
              className="search-form__input"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder={
                isEasyApi
                  ? 'e.g. tesla'
                  : 'Enter keywords or full Facebook group URLs, comma separated'
              }
              disabled={searchLoading}
            />
            <button
              type="button"
              className="search-form__ai-enhance"
              onClick={handleAiEnhance}
              disabled={searchLoading || enhanceLoading}
            >
              {enhanceLoading ? 'Enhancing...' : '✨ AI Enhance'}
            </button>

            {aiSuggestions.length > 0 && (
              <div className="search-form__ai-suggestions">
                <p className="search-form__ai-caption">Click to add keywords:</p>
                <div className="search-form__ai-pills">
                  {aiSuggestions.map((suggestion) => {
                    const isSelected = selectedSuggestions.has(suggestion);
                    return (
                      <button
                        key={suggestion}
                        type="button"
                        className={`search-form__pill ${isSelected ? 'search-form__pill--selected' : ''}`}
                        onClick={() => handleToggleSuggestion(suggestion)}
                        disabled={searchLoading}
                      >
                        {isSelected ? `✓ ${suggestion}` : suggestion}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="search-form__group search-form__group--max-items">
            <label htmlFor="maxItems" className="search-form__label">
              Max Items
            </label>
            <select
              id="maxItems"
              className="search-form__select"
              value={maxItems}
              onChange={(e) => setMaxItems(Number(e.target.value))}
              disabled={searchLoading}
            >
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
              <option value={5}>5</option>
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
            </select>
          </div>
        </div>

        <div className="search-form__actions-row">
          <button
            type="submit"
            className="search-form__submit"
            disabled={searchLoading || enhanceLoading}
          >
            {searchLoading ? 'Searching...' : 'Search'}
          </button>
          
          {searchLoading && currentRunId && searchStatus === 'RUNNING' && (
            <button
              type="button"
              className="search-form__stop-btn"
              onClick={handleStopSearch}
            >
              Stop Search
            </button>
          )}
        </div>
      </form>

      {searchLoading && searchStatus === 'RUNNING' && (
        <div className="search-form__running-status">
          <div className="search-form__spinner"></div>
          <p>Scraping Facebook groups in the background... You can close this tab or navigate away. The run will continue.</p>
        </div>
      )}

      {searchResults && (searchResults.status === 'FAILED' || searchResults.status === 'ABORTED') && (
        <div className="search-form__failed-status">
          <p>Search run {searchResults.status.toLowerCase()}. Please adjust your inputs and try again.</p>
        </div>
      )}

      {searchResults && searchResults.status === 'SUCCEEDED' && (
        <div className="search-form__results">
          <hr className="search-form__divider" />
          
          <div className="search-form__metrics">
            <div className="search-form__metric-card">
              <span className="search-form__metric-label">Total Groups</span>
              <span className="search-form__metric-value">{searchResults.total_groups}</span>
            </div>
            <div className="search-form__metric-card">
              <span className="search-form__metric-label">Unique Queries</span>
              <span className="search-form__metric-value">{uniqueQueriesCount}</span>
            </div>
          </div>

          <div className="search-form__actions">
            <button type="button" className="search-form__btn-download" onClick={downloadCSV}>
              Download CSV
            </button>
            <button type="button" className="search-form__btn-download" onClick={downloadJSON}>
              Download JSON
            </button>
          </div>

          <div className="search-form__tabs">
            <button
              type="button"
              className={`search-form__tab-btn ${activeTab === 'table' ? 'search-form__tab-btn--active' : ''}`}
              onClick={() => setActiveTab('table')}
            >
              Table View
            </button>
            <button
              type="button"
              className={`search-form__tab-btn ${activeTab === 'json' ? 'search-form__tab-btn--active' : ''}`}
              onClick={() => setActiveTab('json')}
            >
              Raw JSON
            </button>
          </div>

          <div className="search-form__tab-content">
            {activeTab === 'table' ? (
              <div className="search-form__table-wrapper">
                <table className="search-form__table">
                  <thead>
                    <tr>
                      <th>Query</th>
                      <th>Group ID</th>
                      <th>Group Name</th>
                      <th>URL</th>
                      <th>Visibility</th>
                      <th>Members</th>
                      <th>Post Frequency</th>
                      <th>Type</th>
                      <th>Join State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {searchResults.groups.map((group, index) => (
                      <tr key={index}>
                        <td>{group.query}</td>
                        <td>{group.id}</td>
                        <td className="search-form__table-name-cell">
                          {group.profilePicture && (
                            <img src={group.profilePicture} alt="" className="search-form__table-avatar" />
                          )}
                          <a href={group.url} target="_blank" rel="noopener noreferrer">
                            {group.name}
                          </a>
                        </td>
                        <td>
                          <a href={group.url} target="_blank" rel="noopener noreferrer" className="search-form__table-url-link">
                            View Group
                          </a>
                        </td>
                        <td>{group.visibility}</td>
                        <td>{group.members}</td>
                        <td>{group.postFrequency}</td>
                        <td>{group.type}</td>
                        <td>{group.joinState}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <pre className="search-form__raw-json">
                {JSON.stringify(searchResults.raw_output, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default SearchForm;

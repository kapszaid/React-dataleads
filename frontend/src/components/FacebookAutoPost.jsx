import React, { useState, useEffect } from 'react';
import './FacebookAutoPost.css';

const rawUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_BASE_URL = rawUrl.endsWith('/') ? rawUrl.slice(0, -1) : rawUrl;

// Helper to mask username & password from proxy string and only show IP:PORT
const formatProxyDisplay = (proxyStr) => {
  if (!proxyStr) return 'Direct';
  const clean = proxyStr.trim();
  const parts = clean.split(':');
  if (parts.length === 4 && !clean.includes('@')) {
    return `${parts[0]}:${parts[1]}`;
  }
  if (parts.length === 2 && !clean.includes('@')) {
    return `${parts[0]}:${parts[1]}`;
  }
  try {
    const url = new URL(clean.includes('://') ? clean : `http://${clean}`);
    return `${url.hostname}${url.port ? ':' + url.port : ''}`;
  } catch (e) {
    return parts.slice(0, 2).join(':');
  }
};

function FacebookAutoPost() {
  const [activeTab, setActiveTab] = useState('runner');

  // Runner state
  const [taskType, setTaskType] = useState('Group Join & Post');
  const [accounts, setAccounts] = useState([]);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [groupCap, setGroupCap] = useState(0);
  const [msgMode, setMsgMode] = useState('single');
  const [singleMsg, setSingleMsg] = useState('');
  const [customMsgs, setCustomMsgs] = useState({});
  const [postUrl, setPostUrl] = useState('');
  const [commentText, setCommentText] = useState('');
  const [isHeadless, setIsHeadless] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [runProgress, setRunProgress] = useState(0);
  const [runStatusText, setRunStatusText] = useState('Idle');
  const [liveLogs, setLiveLogs] = useState([]);

  // Queue state
  const [groupsQueue, setGroupsQueue] = useState([]);
  const [postsQueue, setPostsQueue] = useState([]);

  // Account Manager state
  const [accFormId, setAccFormId] = useState('');
  const [accFormProxy, setAccFormProxy] = useState('');
  const [accFormCookies, setAccFormCookies] = useState('');
  const [accFormStatus, setAccFormStatus] = useState('active');

  // Import Queue state
  const [importTab, setImportTab] = useState('groups');
  const [importGroupUrls, setImportGroupUrls] = useState('');
  const [importGroupPostContent, setImportGroupPostContent] = useState('');
  const [importPostUrls, setImportPostUrls] = useState('');
  const [importPostCommentText, setImportPostCommentText] = useState('');

  // Activity Logs state
  const [activityLogs, setActivityLogs] = useState([]);
  const [logSearch, setLogSearch] = useState('');
  const [logStatusFilter, setLogStatusFilter] = useState('all');

  // Notifications
  const [notification, setNotification] = useState({ type: '', text: '' });

  const showNotification = (text, type = 'info') => {
    setNotification({ text, type });
    setTimeout(() => setNotification({ text: '', type: '' }), 4000);
  };

  const fetchAccounts = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/accounts`);
      if (!res.ok) return;
      const data = await res.json();
      const list = data.accounts || [];
      setAccounts(list);

      if (selectedAccounts.length === 0) {
        const activeIds = list.filter(a => a.status === 'active').map(a => a.account_id);
        setSelectedAccounts(activeIds.length > 0 ? activeIds : list.map(a => a.account_id));
      }
    } catch (err) {
      console.error('Failed to fetch accounts:', err);
    }
  };

  // Poll automation status continuously (supports tab close/reopen & real-time updates)
  const pollAutomationStatus = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/automation/status`);
      if (!res.ok) return;
      const data = await res.json();
      const st = data.state || {};

      setIsRunning(st.is_running || false);
      setRunProgress(st.progress || 0);
      setRunStatusText(st.status_text || 'Idle');
      if (st.logs && st.logs.length > 0) {
        setLiveLogs(st.logs);
      }
      if (data.groups) setGroupsQueue(data.groups);
      if (data.posts) setPostsQueue(data.posts);
      if (data.logs) setActivityLogs(data.logs);
    } catch (err) {
      console.error('Status poll error:', err);
    }
  };

  useEffect(() => {
    fetchAccounts();
    pollAutomationStatus();
  }, []);

  // Poll status ONLY when automation is actively running
  useEffect(() => {
    if (!isRunning) return;

    const intervalId = setInterval(() => {
      pollAutomationStatus();
    }, 3000);

    return () => clearInterval(intervalId);
  }, [isRunning]);

  const toggleAccountSelection = (accId) => {
    if (selectedAccounts.includes(accId)) {
      setSelectedAccounts(selectedAccounts.filter(id => id !== accId));
    } else {
      setSelectedAccounts([...selectedAccounts, accId]);
    }
  };

  const selectAllAccounts = () => setSelectedAccounts(accounts.map(a => a.account_id));
  const deselectAllAccounts = () => setSelectedAccounts([]);

  const handleStartAutomation = async () => {
    if (selectedAccounts.length === 0) {
      showNotification('Please select at least one account.', 'error');
      return;
    }

    setIsRunning(true);
    setRunProgress(5);
    setRunStatusText('Launching automation runner...');

    const payload = {
      task_type: taskType,
      selected_accounts: selectedAccounts,
      group_cap: parseInt(groupCap, 10) || 0,
      is_headless: isHeadless,
      post_content_single: singleMsg,
      post_content_custom: msgMode === 'custom' ? customMsgs : null,
      post_url: postUrl,
      comment_text: commentText
    };

    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/automation/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to start automation');
      }

      showNotification('Automation runner started in background.', 'success');
      pollAutomationStatus();
    } catch (err) {
      setIsRunning(false);
      setRunStatusText('Error starting automation');
      showNotification(err.message, 'error');
    }
  };

  const handleStopAutomation = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/automation/stop`, {
        method: 'POST'
      });
      if (res.ok) {
        showNotification('STOP signal sent. Terminating browser sessions...', 'info');
        setRunStatusText('Stopping...');
        pollAutomationStatus();
      }
    } catch (err) {
      showNotification('Failed to send stop signal.', 'error');
    }
  };

  const handleSaveAccount = async (e) => {
    e.preventDefault();
    if (!accFormId.trim()) {
      showNotification('Account ID is required.', 'error');
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/accounts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accFormId.trim(),
          platform: 'facebook',
          cookies: accFormCookies,
          proxy: accFormProxy,
          status: accFormStatus
        })
      });

      if (!res.ok) throw new Error('Failed to save account');

      showNotification(`Account '${accFormId}' saved successfully.`, 'success');
      setAccFormId('');
      setAccFormProxy('');
      setAccFormCookies('');
      fetchAccounts();
    } catch (err) {
      showNotification(err.message, 'error');
    }
  };

  const handleDeleteAccount = async (accId) => {
    if (!window.confirm(`Delete account '${accId}'?`)) return;
    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/accounts/${accId}`, {
        method: 'DELETE'
      });
      if (!res.ok) throw new Error('Failed to delete account');
      showNotification(`Account '${accId}' deleted.`, 'info');
      fetchAccounts();
    } catch (err) {
      showNotification(err.message, 'error');
    }
  };

  const handleImportGroups = async (e) => {
    e.preventDefault();
    const urls = importGroupUrls.replace(/\r/g, '').split('\n').flatMap(line => line.split(',')).map(u => u.trim()).filter(Boolean);
    if (urls.length === 0) {
      showNotification('Please enter at least one valid Group URL.', 'error');
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/groups/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          urls,
          platform: 'facebook',
          post_content: importGroupPostContent
        })
      });
      if (!res.ok) throw new Error('Import failed');
      const data = await res.json();
      showNotification(`Imported ${data.added_count} group task(s).`, 'success');
      setImportGroupUrls('');
      pollAutomationStatus();
    } catch (err) {
      showNotification(err.message, 'error');
    }
  };

  const handleImportPosts = async (e) => {
    e.preventDefault();
    const urls = importPostUrls.replace(/\r/g, '').split('\n').flatMap(line => line.split(',')).map(u => u.trim()).filter(Boolean);
    if (urls.length === 0) {
      showNotification('Please enter at least one valid Post URL.', 'error');
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/facebook/posts/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          urls,
          comment_text: importPostCommentText,
          platform: 'facebook'
        })
      });
      if (!res.ok) throw new Error('Import failed');
      const data = await res.json();
      showNotification(`Imported ${data.added_count} post target(s).`, 'success');
      setImportPostUrls('');
      pollAutomationStatus();
    } catch (err) {
      showNotification(err.message, 'error');
    }
  };

  const handleClearLogs = async () => {
    if (!window.confirm('Clear all activity logs?')) return;
    try {
      await fetch(`${API_BASE_URL}/api/facebook/logs`, { method: 'DELETE' });
      showNotification('Logs cleared.', 'info');
      pollAutomationStatus();
    } catch (err) {
      showNotification(err.message, 'error');
    }
  };

  const filteredLogs = activityLogs.filter(log => {
    const matchesSearch = !logSearch || 
      (log.account_id && log.account_id.toLowerCase().includes(logSearch.toLowerCase())) ||
      (log.target_url && log.target_url.toLowerCase().includes(logSearch.toLowerCase())) ||
      (log.action && log.action.toLowerCase().includes(logSearch.toLowerCase()));

    const matchesStatus = logStatusFilter === 'all' || log.status === logStatusFilter;

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="fb-auto-container">
      {/* Header */}
      <div className="fb-auto-header">
        <div className="fb-auto-title-group">
          <h1>Facebook Automation</h1>
          <p className="fb-auto-subtitle">
            Group join, posting, notification muting, and post engagement runner.
          </p>
        </div>
      </div>

      {/* Notification */}
      {notification.text && (
        <div className={`fb-card ${notification.type === 'error' ? 'fb-badge failed' : notification.type === 'success' ? 'fb-badge success' : 'fb-badge pending'}`} style={{ width: '100%', marginBottom: 10 }}>
          {notification.text}
        </div>
      )}

      {/* Tabs */}
      <div className="fb-tabs-nav">
        <button
          className={`fb-tab-btn ${activeTab === 'runner' ? 'active' : ''}`}
          onClick={() => setActiveTab('runner')}
        >
          Automation Runner
        </button>
        <button
          className={`fb-tab-btn ${activeTab === 'accounts' ? 'active' : ''}`}
          onClick={() => setActiveTab('accounts')}
        >
          Account Manager ({accounts.length})
        </button>
        <button
          className={`fb-tab-btn ${activeTab === 'import' ? 'active' : ''}`}
          onClick={() => setActiveTab('import')}
        >
          Import Queue ({groupsQueue.length} Groups / {postsQueue.length} Posts)
        </button>
        <button
          className={`fb-tab-btn ${activeTab === 'logs' ? 'active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >
          Activity Logs ({activityLogs.length})
        </button>
      </div>

      {/* TAB 1: RUNNER */}
      {activeTab === 'runner' && (
        <div className="fb-grid-2col">
          <div className="fb-card">
            <h3 className="fb-card-title">Task Setup</h3>

            <div className="fb-form-group">
              <label>Task Type</label>
              <div className="fb-radio-group">
                <label className="fb-radio-label">
                  <input
                    type="radio"
                    name="taskType"
                    value="Group Join & Post"
                    checked={taskType === 'Group Join & Post'}
                    onChange={() => setTaskType('Group Join & Post')}
                  />
                  Group Join & Post
                </label>
                <label className="fb-radio-label">
                  <input
                    type="radio"
                    name="taskType"
                    value="Post Engagement (Like & Comment)"
                    checked={taskType === 'Post Engagement (Like & Comment)'}
                    onChange={() => setTaskType('Post Engagement (Like & Comment)')}
                  />
                  Post Engagement (Like & Comment)
                </label>
              </div>
            </div>

            <div className="fb-form-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <label style={{ margin: 0 }}>Accounts ({selectedAccounts.length}/{accounts.length})</label>
                <div>
                  <button type="button" className="fb-btn-sm" onClick={selectAllAccounts} style={{ marginRight: 4 }}>Select All</button>
                  <button type="button" className="fb-btn-sm" onClick={deselectAllAccounts}>Clear</button>
                </div>
              </div>

              {accounts.length === 0 ? (
                <div style={{ fontSize: 13, color: '#64748b', padding: 8 }}>
                  No accounts found. Add accounts in the Account Manager tab.
                </div>
              ) : (
                <div className="fb-account-checklist">
                  {accounts.map((acc) => (
                    <div key={acc.account_id} className="fb-account-item" onClick={() => toggleAccountSelection(acc.account_id)}>
                      <label onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedAccounts.includes(acc.account_id)}
                          onChange={() => toggleAccountSelection(acc.account_id)}
                        />
                        <span>{acc.account_id}</span>
                      </label>
                      <span className={`fb-status-dot ${acc.status === 'active' ? 'active' : 'inactive'}`} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="fb-form-group">
              <label>
                {taskType === 'Group Join & Post' ? 'Max Groups Per Account' : 'Max Posts Per Account'} (0 = Process ALL)
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <input
                  type="range"
                  min="0"
                  max="50"
                  value={groupCap}
                  onChange={(e) => setGroupCap(e.target.value)}
                  style={{ flex: 1 }}
                />
                <span style={{ fontSize: 14, fontWeight: 600, minWidth: 40 }}>
                  {groupCap == 0 ? 'ALL (0)' : groupCap}
                </span>
              </div>
              <div className="fb-presets">
                <button type="button" className="fb-preset-btn" onClick={() => setGroupCap(0)}>0 (ALL)</button>
                <button type="button" className="fb-preset-btn" onClick={() => setGroupCap(3)}>3</button>
                <button type="button" className="fb-preset-btn" onClick={() => setGroupCap(5)}>5</button>
                <button type="button" className="fb-preset-btn" onClick={() => setGroupCap(10)}>10</button>
              </div>
            </div>

            {taskType === 'Group Join & Post' ? (
              <div className="fb-form-group">
                <label>Message Mode</label>
                <select className="fb-select" value={msgMode} onChange={(e) => setMsgMode(e.target.value)}>
                  <option value="single">Single Message (All Accounts)</option>
                  <option value="custom">Per-Account Custom Messages</option>
                </select>

                {msgMode === 'single' ? (
                  <div style={{ marginTop: 8 }}>
                    <textarea
                      className="fb-textarea"
                      placeholder="Enter post text to publish in groups..."
                      value={singleMsg}
                      onChange={(e) => setSingleMsg(e.target.value)}
                    />
                  </div>
                ) : (
                  <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {selectedAccounts.map(accId => (
                      <div key={accId}>
                        <span style={{ fontSize: 12, fontWeight: 500 }}>Message for {accId}:</span>
                        <textarea
                          className="fb-textarea"
                          style={{ minHeight: 50 }}
                          placeholder={`Message for ${accId}...`}
                          value={customMsgs[accId] || ''}
                          onChange={(e) => setCustomMsgs({ ...customMsgs, [accId]: e.target.value })}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="fb-form-group">
                <label>Comment Text</label>
                <input
                  type="text"
                  className="fb-input"
                  placeholder="Enter comment text for engagement targets..."
                  value={commentText}
                  onChange={(e) => setCommentText(e.target.value)}
                />
              </div>
            )}

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                className="fb-btn-primary"
                disabled={isRunning || selectedAccounts.length === 0}
                onClick={handleStartAutomation}
                style={{ flex: 2 }}
              >
                {isRunning ? 'Running Automation...' : 'Start Automation'}
              </button>
              {isRunning && (
                <button
                  type="button"
                  className="fb-btn-sm danger"
                  onClick={handleStopAutomation}
                  style={{ flex: 1, padding: '12px 16px', fontWeight: 600, fontSize: 13 }}
                >
                  Stop Automation
                </button>
              )}
            </div>
          </div>

          <div className="fb-card">
            <h3 className="fb-card-title">Queue & Status Overview</h3>

            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, fontWeight: 500 }}>
                <span>Status: {runStatusText}</span>
                <span>{runProgress}%</span>
              </div>
              <div className="fb-progress-bar-bg">
                <div className="fb-progress-bar-fill" style={{ width: `${runProgress}%` }} />
              </div>
            </div>

            {liveLogs.length > 0 && (
              <div className="fb-live-console">
                {liveLogs.map((log, index) => (
                  <div key={index}>{log}</div>
                ))}
              </div>
            )}

            <div style={{ marginTop: 16 }}>
              <h4 style={{ margin: '0 0 8px 0', fontSize: 14, fontWeight: 600 }}>
                {taskType === 'Group Join & Post' ? 'Groups Queue' : 'Post Queue'}
              </h4>

              <div className="fb-table-wrapper" style={{ maxHeight: 260 }}>
                <table className="fb-table">
                  <thead>
                    <tr>
                      <th>Target Link</th>
                      <th>Content / Comment</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {taskType === 'Group Join & Post' ? (
                      groupsQueue.length === 0 ? (
                        <tr><td colSpan="3" style={{ textAlign: 'center', color: '#94a3b8' }}>No items in queue.</td></tr>
                      ) : (
                        groupsQueue.slice(0, 15).map((g, idx) => (
                          <tr key={idx}>
                            <td>
                              <a href={g.group_url} target="_blank" rel="noreferrer" className="fb-link">
                                {g.group_url.length > 40 ? g.group_url.slice(0, 37) + '...' : g.group_url}
                              </a>
                            </td>
                            <td>{g.post_content ? (g.post_content.length > 30 ? g.post_content.slice(0, 27) + '...' : g.post_content) : '—'}</td>
                            <td>
                              <span className={`fb-badge ${g.status}`}>{g.status}</span>
                            </td>
                          </tr>
                        ))
                      )
                    ) : (
                      postsQueue.length === 0 ? (
                        <tr><td colSpan="3" style={{ textAlign: 'center', color: '#94a3b8' }}>No items in queue.</td></tr>
                      ) : (
                        postsQueue.slice(0, 15).map((p, idx) => (
                          <tr key={idx}>
                            <td>
                              <a href={p.post_url} target="_blank" rel="noreferrer" className="fb-link">
                                {p.post_url.length > 40 ? p.post_url.slice(0, 37) + '...' : p.post_url}
                              </a>
                            </td>
                            <td>{p.comment_text || '—'}</td>
                            <td>
                              <span className={`fb-badge ${p.status}`}>{p.status}</span>
                            </td>
                          </tr>
                        ))
                      )
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: ACCOUNTS */}
      {activeTab === 'accounts' && (
        <div className="fb-grid-2col">
          <div className="fb-card">
            <h3 className="fb-card-title">Accounts</h3>
            <div className="fb-stats-grid">
              <div className="fb-stat-card">
                <div className="fb-stat-val">{accounts.length}</div>
                <div className="fb-stat-lbl">Total</div>
              </div>
              <div className="fb-stat-card">
                <div className="fb-stat-val" style={{ color: '#16a34a' }}>
                  {accounts.filter(a => a.status === 'active').length}
                </div>
                <div className="fb-stat-lbl">Active</div>
              </div>
            </div>

            <div className="fb-table-wrapper">
              <table className="fb-table">
                <thead>
                  <tr>
                    <th>Account ID</th>
                    <th>Proxy</th>
                    <th>Cookies</th>
                    <th>Status</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.length === 0 ? (
                    <tr><td colSpan="5" style={{ textAlign: 'center', color: '#94a3b8' }}>No accounts.</td></tr>
                  ) : (
                    accounts.map(acc => (
                      <tr key={acc.account_id}>
                        <td style={{ fontWeight: 600 }}>{acc.account_id}</td>
                        <td>{formatProxyDisplay(acc.proxy)}</td>
                        <td>{acc.cookies ? `${acc.cookies.length} cookies` : 'None'}</td>
                        <td>
                          <span className={`fb-badge ${acc.status}`}>{acc.status}</span>
                        </td>
                        <td>
                          <button
                            className="fb-btn-sm danger"
                            onClick={() => handleDeleteAccount(acc.account_id)}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="fb-card">
            <h3 className="fb-card-title">Add / Update Account</h3>
            <form onSubmit={handleSaveAccount}>
              <div className="fb-form-group">
                <label>Account ID *</label>
                <input
                  type="text"
                  className="fb-input"
                  placeholder="e.g. fb_account_1"
                  value={accFormId}
                  onChange={(e) => setAccFormId(e.target.value)}
                  required
                />
              </div>

              <div className="fb-form-group">
                <label>Proxy (Optional)</label>
                <input
                  type="text"
                  className="fb-input"
                  placeholder="IP:PORT:USER:PASS or http://user:pass@ip:port"
                  value={accFormProxy}
                  onChange={(e) => setAccFormProxy(e.target.value)}
                />
              </div>

              <div className="fb-form-group">
                <label>Cookies (JSON or string)</label>
                <textarea
                  className="fb-textarea"
                  placeholder='[{"name": "c_user", "value": "..."}]'
                  value={accFormCookies}
                  onChange={(e) => setAccFormCookies(e.target.value)}
                />
              </div>

              <div className="fb-form-group">
                <label>Status</label>
                <select
                  className="fb-select"
                  value={accFormStatus}
                  onChange={(e) => setAccFormStatus(e.target.value)}
                >
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </select>
              </div>

              <button type="submit" className="fb-btn-primary">
                Save Account
              </button>
            </form>
          </div>
        </div>
      )}

      {/* TAB 3: IMPORT QUEUE */}
      {activeTab === 'import' && (
        <div className="fb-card">
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button
              className={`fb-tab-btn ${importTab === 'groups' ? 'active' : ''}`}
              onClick={() => setImportTab('groups')}
            >
              Import Group Tasks
            </button>
            <button
              className={`fb-tab-btn ${importTab === 'posts' ? 'active' : ''}`}
              onClick={() => setImportTab('posts')}
            >
              Import Post Engagement Targets
            </button>
          </div>

          {importTab === 'groups' ? (
            <form onSubmit={handleImportGroups}>
              <div className="fb-form-group">
                <label>Group URLs (One per line or comma-separated) *</label>
                <textarea
                  className="fb-textarea"
                  style={{ minHeight: 140 }}
                  placeholder="https://www.facebook.com/groups/..."
                  value={importGroupUrls}
                  onChange={(e) => setImportGroupUrls(e.target.value)}
                  required
                />
              </div>

              <button type="submit" className="fb-btn-primary" style={{ width: 'auto' }}>
                Import Group Tasks
              </button>
            </form>
          ) : (
            <form onSubmit={handleImportPosts}>
              <div className="fb-form-group">
                <label>Post URLs (One per line or comma-separated) *</label>
                <textarea
                  className="fb-textarea"
                  style={{ minHeight: 140 }}
                  placeholder="https://www.facebook.com/..."
                  value={importPostUrls}
                  onChange={(e) => setImportPostUrls(e.target.value)}
                  required
                />
              </div>

              <button type="submit" className="fb-btn-primary" style={{ width: 'auto' }}>
                Import Post Targets
              </button>
            </form>
          )}
        </div>
      )}

      {/* TAB 4: ACTIVITY LOGS */}
      {activeTab === 'logs' && (
        <div className="fb-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 className="fb-card-title" style={{ border: 'none', margin: 0, padding: 0 }}>Activity Logs</h3>
            <button className="fb-btn-sm danger" onClick={handleClearLogs}>Clear Logs</button>
          </div>

          <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
            <input
              type="text"
              className="fb-input"
              placeholder="Search logs..."
              value={logSearch}
              onChange={(e) => setLogSearch(e.target.value)}
              style={{ flex: 2 }}
            />
            <select
              className="fb-select"
              value={logStatusFilter}
              onChange={(e) => setLogStatusFilter(e.target.value)}
              style={{ flex: 1 }}
            >
              <option value="all">All Statuses</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="submitted">Submitted</option>
              <option value="joined">Joined</option>
            </select>
          </div>

          <div className="fb-table-wrapper" style={{ maxHeight: 400 }}>
            <table className="fb-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Account ID</th>
                  <th>Action</th>
                  <th>Target URL</th>
                  <th>Status</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.length === 0 ? (
                  <tr><td colSpan="6" style={{ textAlign: 'center', color: '#94a3b8' }}>No logs.</td></tr>
                ) : (
                  filteredLogs.map((log, idx) => (
                    <tr key={idx}>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#64748b' }}>{log.timestamp}</td>
                      <td style={{ fontWeight: 600 }}>{log.account_id}</td>
                      <td>{log.action}</td>
                      <td>
                        <a href={log.target_url} target="_blank" rel="noreferrer" className="fb-link">
                          {log.target_url.length > 35 ? log.target_url.slice(0, 32) + '...' : log.target_url}
                        </a>
                      </td>
                      <td>
                        <span className={`fb-badge ${log.status}`}>{log.status}</span>
                      </td>
                      <td style={{ fontSize: 12, color: '#475569' }}>{log.note || '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default FacebookAutoPost;

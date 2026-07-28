import React, { useState } from 'react';
import './Login.css';

const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : 'https://react-dataleads-9eb2bd8b.fastapicloud.dev';

function Login({ onLoginSuccess }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      setErrorMessage('Please fill in all fields.');
      return;
    }
    setLoading(true);
    setErrorMessage('');
    try {
      const response = await fetch(`${API_BASE_URL}/api/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: username.trim(),
          password: password,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Login failed.');
      }

      const data = await response.json();
      localStorage.setItem('username', data.username);
      onLoginSuccess(data.username);
    } catch (err) {
      console.error(err);
      setErrorMessage(err.message || 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-card__glow"></div>
        <div className="login-card__content">
          <header className="login-card__header">
            <div className="login-card__logo-wrapper">
              <span className="login-card__logo">🚀</span>
            </div>
            <h1 className="login-card__title">Welcome Back</h1>
            <p className="login-card__subtitle">Please enter your credentials to access DataLeads</p>
          </header>

          <form onSubmit={handleSubmit} className="login-card__form">
            {errorMessage && (
              <div className="login-card__error-alert">
                <span className="login-card__error-icon">⚠️</span>
                <span className="login-card__error-text">{errorMessage}</span>
              </div>
            )}

            <div className="login-card__form-group">
              <label htmlFor="login-username" className="login-card__label">Username / Email</label>
              <input
                id="login-username"
                type="text"
                className="login-card__input"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="login-card__form-group">
              <label htmlFor="login-password" className="login-card__label">Password</label>
              <input
                id="login-password"
                type="password"
                className="login-card__input"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>

            <button
              id="login-submit-btn"
              type="submit"
              className="login-card__submit-btn"
              disabled={loading}
            >
              {loading ? (
                <div className="login-card__spinner-container">
                  <div className="login-card__spinner"></div>
                  <span>Signing In...</span>
                </div>
              ) : (
                'Sign In'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default Login;

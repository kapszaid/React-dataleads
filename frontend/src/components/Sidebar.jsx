import React, { useState } from 'react';
import './Sidebar.css';

function Sidebar({ activeTab, setActiveTab, onLogout }) {
  const [collapsed, setCollapsed] = useState(false);

  const menuItems = [
    'Facebook Groups Extractor (Apify)',
    'Facebook Auto Post Engine',
    'Telegram Auto Post Engine'
  ];

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar__header">
        {!collapsed && <span className="sidebar__logo">LeadHunter Pro</span>}
        <button
          type="button"
          className="sidebar__toggle"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? '≫' : '≪'}
        </button>
      </div>

      <nav className="sidebar__nav">
        {menuItems.map((item) => (
          <button
            key={item}
            type="button"
            className={`sidebar__nav-item ${activeTab === item ? 'sidebar__nav-item--active' : ''}`}
            onClick={() => setActiveTab(item)}
            title={item}
          >
            <span className="sidebar__nav-text">{item}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar__footer">
        <button
          type="button"
          className="sidebar__logout-btn"
          onClick={onLogout}
          title="Logout"
        >
          {!collapsed && <span className="sidebar__logout-text">Logout</span>}
          <span className="sidebar__logout-icon">↩</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;

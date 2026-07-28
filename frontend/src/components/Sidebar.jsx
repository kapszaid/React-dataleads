import React, { useState } from 'react';
import './Sidebar.css';

function Sidebar({ activeTab, setActiveTab }) {
  const [collapsed, setCollapsed] = useState(false);

  const menuItems = [
    'Facebook Groups Extractor (Apify)'
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
    </aside>
  );
}

export default Sidebar;

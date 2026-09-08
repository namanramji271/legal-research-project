import { useState } from "react";

const NAV_ITEMS = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M4 10.5L12 4l8 6.5V20a1 1 0 01-1 1h-5v-6H10v6H5a1 1 0 01-1-1v-9.5z" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    id: "mapping",
    label: "IPC–BNS mapping",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "search",
    label: "Judgment search",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="11" cy="11" r="6" />
        <path d="M20 20l-4-4" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    id: "question",
    label: "Ask a question",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 18h.01M8.5 8.5a3.5 3.5 0 117 0c0 2-2 2.5-2 3.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="9" />
      </svg>
    ),
  },
  {
    id: "upload",
    label: "Document upload",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M12 15V5m0 0l-3.5 3.5M12 5l3.5 3.5M5 19h14" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
];

export default function Sidebar({ activePage, onNavigate, auth, onLogout }) {
  const [isPinnedOpen, setIsPinnedOpen] = useState(true);
  const [isHovering, setIsHovering] = useState(false);

  const isExpanded = isPinnedOpen || isHovering;

  const isLawyerOrJudge = auth?.role === "lawyer" || auth?.role === "judge";
  const visibleNavItems = NAV_ITEMS.filter((item) => {
    if (item.id === "search" || item.id === "upload") {
      return isLawyerOrJudge;
    }
    return true;
  });

  function handleToggle() {
    setIsPinnedOpen((pinned) => !pinned);
    setIsHovering(false);
  }

  return (
    <aside
      className={`sidebar${isExpanded ? " sidebar-expanded" : " sidebar-collapsed"}${
        isHovering && !isPinnedOpen ? " sidebar-hover" : ""
      }`}
      onMouseEnter={() => {
        if (!isPinnedOpen) {
          setIsHovering(true);
        }
      }}
      onMouseLeave={() => setIsHovering(false)}
    >
      <div className="sidebar-inner">
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <svg
              className="sidebar-brand-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              aria-hidden="true"
            >
              <path d="M6 4h12v16H6z" />
              <path d="M9 8h6M9 12h6M9 16h4" strokeLinecap="round" />
            </svg>
            <span className="sidebar-wordmark">Legal Research</span>
          </div>
          <button
            type="button"
            className="sidebar-toggle"
            onClick={handleToggle}
            aria-label={isPinnedOpen ? "Collapse sidebar" : "Pin sidebar open"}
            aria-expanded={isExpanded}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              {isPinnedOpen ? (
                <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
              ) : (
                <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              )}
            </svg>
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main">
          {visibleNavItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar-link${
                activePage === item.id ? " sidebar-link-active" : ""
              }`}
              aria-current={activePage === item.id ? "page" : undefined}
              onClick={() => onNavigate(item.id)}
              title={!isExpanded ? item.label : undefined}
            >
              <span className="sidebar-link-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="sidebar-label">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div
            className={`sidebar-user${!isExpanded ? " sidebar-user-collapsed" : ""}`}
            title={!isExpanded && auth ? `${auth.username} (${auth.role})` : undefined}
          >
            <div className="sidebar-user-avatar" aria-hidden="true">
              {auth?.username ? auth.username.charAt(0).toUpperCase() : "U"}
            </div>
            {isExpanded && (
              <div className="sidebar-user-info">
                <span className="sidebar-username">{auth?.username || "User"}</span>
                <span className="sidebar-user-role">{auth?.role || ""}</span>
              </div>
            )}
          </div>
          <button
            type="button"
            className={`sidebar-logout-button${!isExpanded ? " sidebar-logout-button-collapsed" : ""}`}
            onClick={onLogout}
            title={!isExpanded ? "Log out" : undefined}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="sidebar-logout-icon"
              aria-hidden="true"
            >
              <path
                d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l3 3m0 0l-3 3m3-3H9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {isExpanded && <span className="sidebar-label">Log out</span>}
          </button>
        </div>
      </div>
    </aside>
  );
}

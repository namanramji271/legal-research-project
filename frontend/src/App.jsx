import { useState } from "react";
import MappingLookup from "./components/MappingLookup.jsx";
import SearchPage from "./components/SearchPage.jsx";
import "./App.css";

const TABS = [
  { id: "mapping", label: "IPC–BNS Mapping" },
  { id: "search", label: "Judgment Search" },
];

function App() {
  const [activeTab, setActiveTab] = useState("mapping");

  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="app-kicker">Legal Research Platform</p>
        <nav className="app-tabs" aria-label="Main">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`app-tab${activeTab === tab.id ? " app-tab-active" : ""}`}
              aria-current={activeTab === tab.id ? "page" : undefined}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        {activeTab === "mapping" ? <MappingLookup /> : <SearchPage />}
      </main>
    </div>
  );
}

export default App;

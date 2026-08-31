import { useState } from "react";
import DashboardPage from "./DashboardPage.jsx";
import DocumentUploadPage from "./DocumentUploadPage.jsx";
import MappingLookup from "./components/MappingLookup.jsx";
import QuestionPage from "./components/QuestionPage.jsx";
import SearchPage from "./components/SearchPage.jsx";
import Sidebar from "./components/Sidebar.jsx";
import "./App.css";

function renderPage(activePage, onNavigate) {
  switch (activePage) {
    case "dashboard":
      return <DashboardPage onNavigate={onNavigate} />;
    case "mapping":
      return <MappingLookup />;
    case "search":
      return <SearchPage />;
    case "question":
      return <QuestionPage />;
    case "upload":
      return <DocumentUploadPage />;
    default:
      return <DashboardPage onNavigate={onNavigate} />;
  }
}

function App() {
  const [activePage, setActivePage] = useState("dashboard");

  return (
    <div className="app-layout">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      <div className="app-content">
        <main className={`app-main${activePage === "dashboard" ? " app-main-dashboard" : ""}`}>
          <div key={activePage} className="page-fade">
            {renderPage(activePage, setActivePage)}
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;

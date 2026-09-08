import { useState } from "react";
import DashboardPage from "./DashboardPage.jsx";
import DocumentUploadPage from "./DocumentUploadPage.jsx";
import MappingLookup from "./components/MappingLookup.jsx";
import QuestionPage from "./components/QuestionPage.jsx";
import SearchPage from "./components/SearchPage.jsx";
import Sidebar from "./components/Sidebar.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import "./App.css";

function renderPage(activePage, onNavigate, auth) {
  const isLawyerOrJudge = auth?.role === "lawyer" || auth?.role === "judge";

  if ((activePage === "search" || activePage === "upload") && !isLawyerOrJudge) {
    return <DashboardPage onNavigate={onNavigate} auth={auth} />;
  }

  switch (activePage) {
    case "dashboard":
      return <DashboardPage onNavigate={onNavigate} auth={auth} />;
    case "mapping":
      return <MappingLookup auth={auth} />;
    case "search":
      return <SearchPage auth={auth} />;
    case "question":
      return <QuestionPage auth={auth} />;
    case "upload":
      return <DocumentUploadPage auth={auth} />;
    default:
      return <DashboardPage onNavigate={onNavigate} auth={auth} />;
  }
}

function App() {
  const [auth, setAuth] = useState(() => {
    try {
      const stored = localStorage.getItem("auth");
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });
  const [authView, setAuthView] = useState("login");
  const [activePage, setActivePage] = useState("dashboard");

  const isLawyerOrJudge = auth?.role === "lawyer" || auth?.role === "judge";

  function handleNavigate(page) {
    if ((page === "search" || page === "upload") && !isLawyerOrJudge) {
      setActivePage("dashboard");
      return;
    }
    setActivePage(page);
  }

  function handleLogout() {
    localStorage.removeItem("auth");
    setAuth(null);
    setActivePage("dashboard");
    setAuthView("login");
  }

  if (!auth) {
    return authView === "signup" ? (
      <SignupPage
        onLogin={(data) => setAuth(data)}
        onSwitchToLogin={() => setAuthView("login")}
      />
    ) : (
      <LoginPage
        onLogin={(data) => setAuth(data)}
        onSwitchToSignup={() => setAuthView("signup")}
      />
    );
  }

  return (
    <div className="app-layout">
      <Sidebar
        activePage={activePage}
        onNavigate={handleNavigate}
        auth={auth}
        onLogout={handleLogout}
      />
      <div className="app-content">
        <main className={`app-main${activePage === "dashboard" ? " app-main-dashboard" : ""}`}>
          <div key={activePage} className="page-fade">
            {renderPage(activePage, handleNavigate, auth)}
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;

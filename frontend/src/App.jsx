import { useState } from "react";
import DashboardPage from "./DashboardPage.jsx";
import DocumentUploadPage from "./DocumentUploadPage.jsx";
import MappingLookup from "./components/MappingLookup.jsx";
import QuestionPage from "./components/QuestionPage.jsx";
import SearchPage from "./components/SearchPage.jsx";
import Sidebar from "./components/Sidebar.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import ComparisonPage from "./pages/ComparisonPage.jsx";
import CounterArgumentsPage from "./pages/CounterArgumentsPage.jsx";
import "./App.css";


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
  const [compareNames, setCompareNames] = useState([]);
  const [counterArgumentNames, setCounterArgumentNames] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchHasSearched, setSearchHasSearched] = useState(false);

  const isLawyerOrJudge = auth?.role === "lawyer" || auth?.role === "judge";

  function handleNavigate(page) {
    if ((page === "search" || page === "upload") && !isLawyerOrJudge) {
      setActivePage("dashboard");
      return;
    }
    setActivePage(page);
  }

  function handleCompare(caseNames) {
    setCompareNames(caseNames);
    setActivePage("compare");
  }

  function handleBackFromCompare() {
    setCompareNames([]);
    setActivePage("search");
  }

  function handleFindCounterArguments(caseNames) {
    setCounterArgumentNames(caseNames);
    setActivePage("counter-arguments");
  }

  function handleBackFromCounterArguments() {
    setCounterArgumentNames([]);
    setActivePage("search");
  }

  function handleLogout() {
    localStorage.removeItem("auth");
    setAuth(null);
    setActivePage("dashboard");
    setAuthView("login");
    setCompareNames([]);
    setCounterArgumentNames([]);
    setSearchQuery("");
    setSearchResults([]);
    setSearchHasSearched(false);
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

  function renderPage() {
    if ((activePage === "search" || activePage === "upload") && !isLawyerOrJudge) {
      return <DashboardPage onNavigate={handleNavigate} auth={auth} />;
    }

    if (activePage === "compare") {
      // Only judges can reach compare page
      if (auth?.role !== "judge" || compareNames.length < 2) {
        return <DashboardPage onNavigate={handleNavigate} auth={auth} />;
      }
      return (
        <ComparisonPage
          caseNames={compareNames}
          onBack={handleBackFromCompare}
        />
      );
    }

    if (activePage === "counter-arguments") {
      // Lawyer and judge can reach counter-arguments page
      if (!isLawyerOrJudge || counterArgumentNames.length < 1) {
        return <DashboardPage onNavigate={handleNavigate} auth={auth} />;
      }
      return (
        <CounterArgumentsPage
          caseNames={counterArgumentNames}
          onBack={handleBackFromCounterArguments}
        />
      );
    }

    switch (activePage) {
      case "dashboard":
        return <DashboardPage onNavigate={handleNavigate} auth={auth} />;
      case "mapping":
        return <MappingLookup auth={auth} />;
      case "search":
        return (
          <SearchPage
            auth={auth}
            onCompare={handleCompare}
            onFindCounterArguments={handleFindCounterArguments}
            query={searchQuery}
            setQuery={setSearchQuery}
            results={searchResults}
            setResults={setSearchResults}
            hasSearched={searchHasSearched}
            setHasSearched={setSearchHasSearched}
          />
        );
      case "question":
        return <QuestionPage auth={auth} />;
      case "upload":
        return <DocumentUploadPage auth={auth} />;
      default:
        return <DashboardPage onNavigate={handleNavigate} auth={auth} />;
    }
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
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;

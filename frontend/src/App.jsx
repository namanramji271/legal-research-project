import { useEffect, useState } from "react";

function App() {
  const [status, setStatus] = useState("loading...");

  useEffect(() => {
    fetch("http://localhost:8000/")
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch((err) => setStatus("error: " + err.message));
  }, []);

  return (
    <div className="p-8 text-xl">
      Backend says: {status}
    </div>
  );
}

export default App;

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { connect } from "./lib/bridge";

connect();
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);

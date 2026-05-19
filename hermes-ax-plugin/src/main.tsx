import React from "react";
import { App } from "./components/App";
import "./styles/plugin.css";

const registry = (window as any).__HERMES_PLUGINS__;

if (registry) {
  registry.register("hermes-ax", App);
} else {
  console.error("[hermes-ax] window.__HERMES_PLUGINS__ not found");
}

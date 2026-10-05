// A React component.
import React from 'react';

export function App({ items = [] }) {
  const style = { color: 'red' };
  return (
    <div className="app" style={{ margin: 0 }}>
      {items.map((i) => <span key={i}>{`item ${i}`}</span>)}
    </div>
  );
}

const helper = () => {};

class Store {
  state = { a: 1 };
  static create() { return new Store(); }
}

module.exports = { App, helper };

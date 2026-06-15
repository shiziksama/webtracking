import './style.css';

const app = document.querySelector<HTMLDivElement>('#app');

if (!app) {
  throw new Error('Application root was not found');
}

app.innerHTML = `
  <main>
    <h1>Web Tracking</h1>
    <p>Project scaffold is ready.</p>
  </main>
`;

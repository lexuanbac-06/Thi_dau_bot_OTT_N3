import {createRoot} from 'react-dom/client';
import App from './App';
import './theme.css';
import './styles.css';
import './ui.css';
import {initTheme} from './theme';
initTheme();
createRoot(document.getElementById('root')!).render(<App/>);

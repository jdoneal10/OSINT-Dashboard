import { createBrowserRouter, type RouteObject } from 'react-router'
import AppShell from './components/AppShell'
import BorderPage from './pages/BorderPage'
import MapPage from './pages/MapPage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <MapPage /> },
      { path: 'border', element: <BorderPage /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)

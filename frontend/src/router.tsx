import { createBrowserRouter, type RouteObject } from 'react-router'
import AppShell from './components/AppShell'
import BorderPage from './pages/BorderPage'
import ClusterPage from './pages/ClusterPage'
import DesignationsPage from './pages/DesignationsPage'
import DocumentPage from './pages/DocumentPage'
import LabelingPage from './pages/LabelingPage'
import MapPage from './pages/MapPage'
import NewsPage from './pages/NewsPage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <MapPage /> },
      { path: 'border', element: <BorderPage /> },
      { path: 'news', element: <NewsPage /> },
      { path: 'news/:id', element: <DocumentPage /> },
      { path: 'clusters/:id', element: <ClusterPage /> },
      { path: 'designations', element: <DesignationsPage /> },
      { path: 'labeling', element: <LabelingPage /> },
      { path: 'labeling/:id', element: <LabelingPage /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)

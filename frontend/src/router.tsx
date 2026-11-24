import { createBrowserRouter, type RouteObject } from 'react-router'
import AppShell from './components/AppShell'
import BorderPage from './pages/BorderPage'
import ClusterPage from './pages/ClusterPage'
import DesignationsPage from './pages/DesignationsPage'
import DocumentPage from './pages/DocumentPage'
import GridLabelingPage from './pages/GridLabelingPage'
import LabelingPage from './pages/LabelingPage'
import MapPage from './pages/MapPage'
import MergeReviewPage from './pages/MergeReviewPage'
import NewsPage from './pages/NewsPage'
import PersonPage from './pages/PersonPage'
import PersonsPage from './pages/PersonsPage'
import PriorityPage from './pages/PriorityPage'
import UxsLabelingPage from './pages/UxsLabelingPage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <MapPage /> },
      { path: 'border', element: <BorderPage /> },
      { path: 'news', element: <NewsPage /> },
      { path: 'threats', element: <NewsPage threats key="threats" /> },
      { path: 'news/:id', element: <DocumentPage /> },
      { path: 'clusters/:id', element: <ClusterPage /> },
      { path: 'priority', element: <PriorityPage /> },
      { path: 'priority/:topic', element: <PriorityPage /> },
      { path: 'persons', element: <PersonsPage /> },
      { path: 'persons/review', element: <MergeReviewPage /> },
      { path: 'persons/:id', element: <PersonPage /> },
      { path: 'designations', element: <DesignationsPage /> },
      { path: 'labeling', element: <LabelingPage /> },
      { path: 'labeling/grid', element: <GridLabelingPage /> },
      { path: 'labeling/uxs', element: <UxsLabelingPage /> },
      { path: 'labeling/:id', element: <LabelingPage /> },
    ],
  },
]

export const createRouter = () => createBrowserRouter(routes)

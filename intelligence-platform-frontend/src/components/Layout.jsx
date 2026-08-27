import Sidebar from './Sidebar';
import TopNav from './TopNav';
import Footer from './Footer';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <TopNav />
      <Sidebar />
      <div className="flex-1 flex flex-col md:ml-sidebar-width pt-16">
        <main className="flex-1 overflow-y-auto p-container-margin">
          {children}
        </main>
        <Footer />
      </div>
    </div>
  );
}

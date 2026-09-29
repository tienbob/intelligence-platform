import Sidebar from './Sidebar';
import TopNav from './TopNav';
import Footer from './Footer';
import MobileNav from './MobileNav';

export default function Layout({ children }) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <TopNav />
      <Sidebar />
      {/* pb-16 keeps content/footer clear of the MobileNav bottom bar on small screens */}
      <div className="flex-1 flex flex-col md:ml-sidebar-width pt-16 pb-16 md:pb-0">
        <main className="flex-1 overflow-y-auto p-container-margin">
          {children}
        </main>
        <Footer />
      </div>
      <MobileNav />
    </div>
  );
}

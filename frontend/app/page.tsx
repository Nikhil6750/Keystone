import { Header } from '@/components/common';
import { Button, Card, CardHeader, CardTitle, CardContent } from '@/components/ui';
import { APP_CONFIG } from '@/lib/constants';

export default function Home() {
  return (
    <div className="bg-background flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto w-full max-w-7xl flex-1 space-y-6 p-6 md:p-10">
        <div className="flex flex-col space-y-2">
          <h2 className="text-3xl font-bold tracking-tight">Welcome to {APP_CONFIG.name}</h2>
          <p className="text-muted-foreground">{APP_CONFIG.description}</p>
        </div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          <Card className="glass-panel">
            <CardHeader>
              <CardTitle>Architecture Ready</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-muted-foreground text-sm">
                Next.js 15 App Router, TypeScript, Tailwind CSS, and shadcn/ui are initialized with
                a scalable SaaS architecture.
              </p>
              <Button variant="default" size="sm">
                Get Started
              </Button>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

declare global {
  interface Window {
    HermesSDK: HermesSDK;
  }
}

export interface HermesSDK {
  React: typeof import("react");
  ReactDOM: typeof import("react-dom");
  JSXRuntime: typeof import("react/jsx-runtime");
  ui: HermesUI;
  registerPlugin: (plugin: PluginRegistration) => void;
  getPluginApiBase: () => string;
  cn: (...classes: (string | undefined | null | false)[]) => string;
}

export interface PluginRegistration {
  id: string;
  component: React.ComponentType;
}

export interface HermesUI {
  Card: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  CardTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>>;
  CardDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>>;
  CardContent: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  Badge: React.FC<{ variant?: "default" | "secondary" | "destructive" | "outline"; className?: string; children?: React.ReactNode }>;
  Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "secondary" | "destructive" | "outline" | "ghost" | "link"; size?: "default" | "sm" | "lg" | "icon" }>;
  Tabs: React.FC<{ value?: string; onValueChange?: (v: string) => void; defaultValue?: string; className?: string; children?: React.ReactNode }>;
  TabsList: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  TabsTrigger: React.FC<{ value: string; className?: string; children?: React.ReactNode }>;
  TabsContent: React.FC<{ value: string; className?: string; children?: React.ReactNode }>;
  Dialog: React.FC<{ open?: boolean; onOpenChange?: (open: boolean) => void; children?: React.ReactNode }>;
  DialogContent: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  DialogHeader: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  DialogTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>>;
  DialogDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>>;
  DialogFooter: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>>;
  Textarea: React.FC<React.TextareaHTMLAttributes<HTMLTextAreaElement>>;
  Select: React.FC<{ value?: string; onValueChange?: (v: string) => void; children?: React.ReactNode }>;
  SelectTrigger: React.FC<React.HTMLAttributes<HTMLButtonElement> & { children?: React.ReactNode }>;
  SelectValue: React.FC<{ placeholder?: string }>;
  SelectContent: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  SelectItem: React.FC<{ value: string; children?: React.ReactNode }>;
  ScrollArea: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  Separator: React.FC<React.HTMLAttributes<HTMLHRElement>>;
  Tooltip: React.FC<{ children?: React.ReactNode }>;
  TooltipTrigger: React.FC<React.HTMLAttributes<HTMLButtonElement> & { asChild?: boolean }>;
  TooltipContent: React.FC<React.HTMLAttributes<HTMLDivElement>>;
  TooltipProvider: React.FC<{ children?: React.ReactNode }>;
}

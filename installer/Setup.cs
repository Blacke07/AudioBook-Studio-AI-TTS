// AudioBook Studio setup: a welcome page, step-by-step progress and a finish page. bootstrap.ps1 does the work.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// The application's dark palette (app/web/style.css), so setup looks like the app it installs.
static class Theme {
    public static readonly Color Bg=Color.FromArgb(0x16,0x13,0x11), Surface=Color.FromArgb(0x20,0x1c,0x19),
        Surface2=Color.FromArgb(0x27,0x22,0x1e), Ink=Color.FromArgb(0xf1,0xe8,0xdd), Muted=Color.FromArgb(0xa5,0x97,0x8a),
        Line=Color.FromArgb(0x38,0x31,0x2b), Accent=Color.FromArgb(0xe2,0x7a,0x4b), AccentInk=Color.FromArgb(0x1b,0x14,0x11),
        AccentSoft=Color.FromArgb(0x3d,0x2a,0x20), Ok=Color.FromArgb(0x5f,0xbf,0x9b), OkSoft=Color.FromArgb(0x1f,0x3a,0x31),
        Warn=Color.FromArgb(0xe0,0xa6,0x4a), WarnSoft=Color.FromArgb(0x3b,0x2f,0x1a), Bad=Color.FromArgb(0xef,0x7b,0x72),
        BadSoft=Color.FromArgb(0x43,0x22,0x1f);
    // Layout is written for 96 DPI and scaled once; fonts are in points and follow the screen's DPI by themselves.
    public static readonly float K=ScreenScale();
    public static Font Sans(float size) { return new Font("Segoe UI",size); }
    public static Font SansBold(float size) { return new Font("Segoe UI Semibold",size); }
    public static Font Serif(float size) { return new Font("Georgia",size,FontStyle.Bold); }
    // Shared fonts for controls that repaint often (the step spinner repaints every 40 ms).
    public static readonly Font Step=Sans(10.5f), StepBold=SansBold(10.5f), CardTitle=SansBold(11), CardDetail=Sans(9.5f);

    static float ScreenScale() { using(var g=Graphics.FromHwnd(IntPtr.Zero)) return g.DpiX/96f; }

    public static GraphicsPath Round(RectangleF r,float radius) {
        var path=new GraphicsPath(); float d=Math.Min(radius*2,Math.Min(r.Width,r.Height));
        path.AddArc(r.X,r.Y,d,d,180,90); path.AddArc(r.Right-d,r.Y,d,d,270,90);
        path.AddArc(r.Right-d,r.Bottom-d,d,d,0,90); path.AddArc(r.X,r.Bottom-d,d,d,90,90);
        path.CloseFigure(); return path;
    }
}

// Base for the custom-painted controls below. Inner coordinates are 96-DPI units multiplied by Theme.K.
class Painted : Control {
    protected static readonly float K=Theme.K;
    public Painted() {
        SetStyle(ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.UserPaint|
                 ControlStyles.ResizeRedraw|ControlStyles.SupportsTransparentBackColor,true);
        BackColor=Color.Transparent; ForeColor=Theme.Ink; Font=Theme.Sans(10);
    }
    protected static Graphics Smooth(PaintEventArgs e) { e.Graphics.SmoothingMode=SmoothingMode.AntiAlias; return e.Graphics; }
    protected static Rectangle Box(float x,float y,float width,float height) {
        return new Rectangle((int)(x*K),(int)(y*K),(int)(width*K),(int)(height*K));
    }
}

class Pill : Painted {
    public Color Fill=Theme.Surface2;
    public bool Ellipsis;
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e);
        using(var path=Theme.Round(new RectangleF(0,0,Width-1,Height-1),Math.Min(8*K,Height/2f)))
        using(var brush=new SolidBrush(Fill)) g.FillPath(brush,path);
        TextRenderer.DrawText(g,Text,Font,new Rectangle((int)(10*K),0,Width-(int)(20*K),Height),ForeColor,
            TextFormatFlags.VerticalCenter|TextFormatFlags.Left|TextFormatFlags.SingleLine|
            (Ellipsis?TextFormatFlags.PathEllipsis:TextFormatFlags.EndEllipsis));
    }
}

class Push : Painted, IButtonControl {
    public bool Primary;
    bool hover;
    public Push(string text,bool primary) { Text=text; Primary=primary; Cursor=Cursors.Hand; Font=Theme.SansBold(10); TabStop=true; }
    public DialogResult DialogResult { get; set; }
    public void NotifyDefault(bool value) { }
    public void PerformClick() { if(Enabled) OnClick(EventArgs.Empty); }
    protected override void OnMouseEnter(EventArgs e) { hover=true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hover=false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnKeyUp(KeyEventArgs e) { if(e.KeyCode==Keys.Space||e.KeyCode==Keys.Enter) PerformClick(); base.OnKeyUp(e); }
    protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
    protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
    protected override void OnTextChanged(EventArgs e) { Invalidate(); base.OnTextChanged(e); }
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e);
        Color fill=Primary ? (hover?ControlPaint.Light(Theme.Accent,0.15f):Theme.Accent) : (hover?Theme.Line:Theme.Surface2);
        using(var path=Theme.Round(new RectangleF(0.5f,0.5f,Width-1.5f,Height-1.5f),9*K)) {
            using(var brush=new SolidBrush(fill)) g.FillPath(brush,path);
            if(!Primary||Focused) using(var pen=new Pen(Focused?Theme.Ink:Theme.Line,Focused?1.5f*K:K)) g.DrawPath(pen,path);
        }
        TextRenderer.DrawText(g,Text,Font,ClientRectangle,Primary?Theme.AccentInk:Theme.Ink,
            TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine);
    }
}

// A large selectable option on the welcome page.
class OptionCard : Painted {
    public string Detail="";
    bool selected, hover;
    public event EventHandler Chosen;
    public OptionCard(string title) { Text=title; Cursor=Cursors.Hand; }
    public bool Selected { get { return selected; } set { selected=value; Invalidate(); } }
    protected override void OnMouseEnter(EventArgs e) { hover=true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hover=false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnClick(EventArgs e) { if(Enabled && Chosen!=null) Chosen(this,e); base.OnClick(e); }
    protected override void OnEnabledChanged(EventArgs e) { Cursor=Enabled?Cursors.Hand:Cursors.Default; Invalidate(); base.OnEnabledChanged(e); }
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e);
        using(var path=Theme.Round(new RectangleF(K,K,Width-2*K,Height-2*K),12*K)) {
            using(var brush=new SolidBrush(selected?Theme.AccentSoft:(hover&&Enabled?Theme.Surface2:Theme.Surface))) g.FillPath(brush,path);
            using(var pen=new Pen(selected?Theme.Accent:Theme.Line,(selected?2:1)*K)) g.DrawPath(pen,path);
        }
        var dot=new RectangleF(18*K,18*K,18*K,18*K);
        using(var pen=new Pen(selected?Theme.Accent:Theme.Muted,2*K)) g.DrawEllipse(pen,dot);
        if(selected) using(var brush=new SolidBrush(Theme.Accent)) g.FillEllipse(brush,dot.X+4.5f*K,dot.Y+4.5f*K,9*K,9*K);
        TextRenderer.DrawText(g,Text,Theme.CardTitle,Box(48,11,Width/K-62,32),Enabled?Theme.Ink:Theme.Muted,
            TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis);
        TextRenderer.DrawText(g,Detail,Theme.CardDetail,Box(48,44,Width/K-62,Height/K-48),Theme.Muted,
            TextFormatFlags.Left|TextFormatFlags.WordBreak);
    }
}

class Toggle : Painted {
    bool on=true;
    public Toggle(string text) { Text=text; Cursor=Cursors.Hand; TabStop=true; }
    public bool Checked { get { return on; } set { on=value; Invalidate(); } }
    protected override void OnClick(EventArgs e) { Checked=!on; base.OnClick(e); }
    protected override void OnKeyUp(KeyEventArgs e) { if(e.KeyCode==Keys.Space) Checked=!on; base.OnKeyUp(e); }
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e); float top=(Height-18*K)/2;
        using(var path=Theme.Round(new RectangleF(K,top,18*K,18*K),5*K)) {
            using(var brush=new SolidBrush(on?Theme.Accent:Theme.Surface2)) g.FillPath(brush,path);
            using(var pen=new Pen(on?Theme.Accent:Theme.Muted,1.5f*K)) g.DrawPath(pen,path);
        }
        if(on) using(var pen=new Pen(Theme.AccentInk,2.2f*K))
            g.DrawLines(pen,new[] { new PointF(5*K,top+9*K),new PointF(8.5f*K,top+12.5f*K),new PointF(15*K,top+5*K) });
        TextRenderer.DrawText(g,Text,Font,new Rectangle((int)(28*K),0,Width-(int)(28*K),Height),Theme.Ink,
            TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine);
    }
}

enum StepState { Pending, Active, Done, Failed }

class StepRow : Painted {
    public static float Spin;
    StepState state;
    public StepRow(string text) { Text=text; Font=Theme.Step; }
    public StepState State { get { return state; } set { state=value; Invalidate(); } }
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e); float top=(Height-20*K)/2; var c=new RectangleF(2*K,top,20*K,20*K);
        if(state==StepState.Done) {
            using(var brush=new SolidBrush(Theme.OkSoft)) g.FillEllipse(brush,c);
            using(var pen=new Pen(Theme.Ok,2.2f*K))
                g.DrawLines(pen,new[] { new PointF(7*K,top+10.5f*K),new PointF(10.5f*K,top+14*K),new PointF(17*K,top+6.5f*K) });
        } else if(state==StepState.Failed) {
            using(var brush=new SolidBrush(Theme.BadSoft)) g.FillEllipse(brush,c);
            using(var pen=new Pen(Theme.Bad,2.2f*K)) { g.DrawLine(pen,8*K,top+6*K,16*K,top+14*K); g.DrawLine(pen,16*K,top+6*K,8*K,top+14*K); }
        } else if(state==StepState.Active) {
            using(var pen=new Pen(Theme.AccentSoft,2.5f*K)) g.DrawEllipse(pen,c);
            using(var pen=new Pen(Theme.Accent,2.5f*K) { StartCap=LineCap.Round,EndCap=LineCap.Round }) g.DrawArc(pen,c,Spin,100);
        } else using(var pen=new Pen(Theme.Line,2*K)) g.DrawEllipse(pen,c);
        Color ink=state==StepState.Pending?Theme.Muted:(state==StepState.Failed?Theme.Bad:Theme.Ink);
        TextRenderer.DrawText(g,Text,state==StepState.Active?Theme.StepBold:Font,new Rectangle((int)(34*K),0,Width-(int)(34*K),Height),ink,
            TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine);
    }
}

class Bar : Painted {
    public float Value=-1;   // 0..1, or -1 while the length of the current step is unknown
    public float Offset;
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e); var r=new RectangleF(0,0,Width,Height);
        using(var path=Theme.Round(r,Height/2f)) using(var brush=new SolidBrush(Theme.Surface2)) g.FillPath(brush,path);
        RectangleF fill=Value>=0 ? new RectangleF(0,0,Math.Max(Height,Width*Math.Min(1,Value)),Height)
                                 : new RectangleF(((Offset%1.3f)-0.3f)*Width,0,Width*0.3f,Height);
        g.SetClip(r);
        using(var path=Theme.Round(fill,Height/2f)) using(var brush=new SolidBrush(Theme.Accent)) g.FillPath(brush,path);
    }
}

class BigCheck : Painted {
    protected override void OnPaint(PaintEventArgs e) {
        var g=Smooth(e);
        using(var brush=new SolidBrush(Theme.OkSoft)) g.FillEllipse(brush,1,1,Width-2,Height-2);
        float s=Width/64f;
        using(var pen=new Pen(Theme.Ok,4*s) { StartCap=LineCap.Round,EndCap=LineCap.Round,LineJoin=LineJoin.Round })
            g.DrawLines(pen,new[] { new PointF(19*s,33*s),new PointF(28*s,42*s),new PointF(45*s,24*s) });
    }
}

class Setup : Form {
    const string ModelsFolder="Local Models", Guide="_place models here",
                 GuideHeader="AudioBook Studio - place your model files in this folder";
    static readonly string[] ProfileKeys={"voice_design","custom_voice","base","codec"};
    static Dictionary<string,object> manifestCache;
    const int Width96=780, Height96=640, Edge=36, Inner=Width96-2*Edge;   // layout in 96-DPI units
    static readonly string[] Steps={"Private Python","Application and Python libraries","FFmpeg and Ollama",
                                    "Voice models (Qwen)","Dialogue model (Gemma)","Final check"};
    readonly string root;
    readonly Panel welcome=new Panel(), progress=new Panel(), finish=new Panel();
    readonly OptionCard download=new OptionCard("Download the models for me"), local=new OptionCard("I already have the model files");
    readonly OptionCard standardCard=new OptionCard("Standard"), compactCard=new OptionCard("Compact · experimental");
    readonly Pill gpu=new Pill(), space=new Pill();
    readonly Label note=new Label(), activity=new Label(), amount=new Label(), error=new Label(), progressTitle=new Label(),
                   progressSubtitle=new Label();
    readonly Push install=new Push("Install",true), retry=new Push("Retry",true), openFolder=new Push("Open folder",false),
                  closeProgress=new Push("Close",false);
    readonly Bar bar=new Bar();
    readonly List<StepRow> rows=new List<StepRow>();
    readonly TextBox log=new TextBox();
    readonly LinkLabel details=new LinkLabel();
    readonly Toggle desktopShortcut=new Toggle("Create a desktop shortcut"), startShortcut=new Toggle("Add to the Start menu");
    readonly Timer animation=new Timer { Interval=40 };
    public bool Preview;   // set by RenderPreview: no hardware checks, sample values only
    string session, lastError, currentFile, profile=DefaultProfile();
    bool running, supplied, preparedFolder;
    long freeBytes=-1;
    int current=-1;
    long fileStartBytes; DateTime fileStart;

    [STAThread]
    static int Main(string[] args) {
        if(args.Length>0 && args[0]=="--check-resources") {
            foreach(string name in new string[]{"bootstrap.ps1","install.py","manifest.json","payload.zip","README.md","app.ico"}) {
                using(Stream source=Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                    if(source==null || source.Length==0) return 1;
                }
            }
            return 0;
        }
        if(args.Length>1 && args[0]=="--prepare-local-models") {
            string chosen=args.Length>2?args[2]:DefaultProfile();
            if(!((Dictionary<string,object>)Manifest()["profiles"]).ContainsKey(chosen)) return 2;
            PrepareModelsFolder(args[1],chosen); return 0;
        }
        if(args.Length>3 && args[0]=="--create-shortcuts") { CreateShortcuts(args[1],args[2],args[3]); return 0; }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length>1 && args[0]=="--render-preview") { RenderPreview(args[1]); return 0; }
        Application.Run(new Setup(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)));
        return 0;
    }

    public Setup(string folder) {
        root=folder;
        Text="AudioBook Studio setup"; BackColor=Theme.Bg; ForeColor=Theme.Ink; Font=Theme.Sans(10);
        AutoScaleMode=AutoScaleMode.None; ClientSize=new Size(Width96,Height96);
        FormBorderStyle=FormBorderStyle.FixedSingle; MaximizeBox=false;
        StartPosition=FormStartPosition.CenterScreen; DoubleBuffered=true;
        Icon=AppIcon();
        foreach(var page in new[] { welcome,progress,finish }) { page.Dock=DockStyle.Fill; page.BackColor=Theme.Bg; Controls.Add(page); }
        BuildWelcome(); BuildProgress(); BuildFinish();
        if(Theme.K!=1) Scale(new SizeF(Theme.K,Theme.K));
        ShowPage(welcome);
        animation.Tick+=delegate {
            StepRow.Spin=(StepRow.Spin+12)%360; bar.Offset+=0.02f;
            foreach(var row in rows) if(row.State==StepState.Active) row.Invalidate();
            if(bar.Value<0) bar.Invalidate();
        };
        Shown+=delegate { if(!Preview) CheckComputer(); };
        FormClosing+=delegate(object sender,FormClosingEventArgs e) {
            if(running) {
                MessageBox.Show(this,"Setup is still working. Wait until the current step finishes.","AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Information);
                e.Cancel=true; return;
            }
            RemoveSession();
        };
    }

    // -- pages (coordinates in 96-DPI units; the whole form is scaled once) -----------------------------
    static Label AddText(Control parent,string text,Font font,Color color,int x,int y,int width,int height) {
        var label=new Label { Text=text,Font=font,ForeColor=color,BackColor=Color.Transparent,Bounds=new Rectangle(x,y,width,height) };
        parent.Controls.Add(label); return label;
    }

    void BuildWelcome() {
        welcome.Controls.Add(new PictureBox { Image=Logo(),SizeMode=PictureBoxSizeMode.Zoom,Bounds=new Rectangle(Edge,34,52,52),BackColor=Color.Transparent });
        AddText(welcome,"AudioBook Studio",Theme.Serif(19),Theme.Ink,102,30,600,42);
        AddText(welcome,"Turn English chapters into narrated audiobooks on your own computer.",Theme.Sans(10),Theme.Muted,104,74,640,28);
        AddText(welcome,"Installs in this folder",Theme.Sans(9.5f),Theme.Muted,Edge,112,400,24);
        welcome.Controls.Add(new Pill { Text=root,Ellipsis=true,Bounds=new Rectangle(Edge,138,Inner,38) });
        gpu.Bounds=new Rectangle(Edge,186,420,34); gpu.Text="Checking the graphics card…"; gpu.Font=Theme.Sans(9.5f);
        space.Bounds=new Rectangle(Edge+432,186,220,34); space.Text="Checking free space…"; space.Font=Theme.Sans(9.5f);
        welcome.Controls.Add(gpu); welcome.Controls.Add(space);
        AddText(welcome,"Model set",Theme.Sans(9.5f),Theme.Muted,Edge,232,500,24);
        standardCard.Detail="Best quality for new voices. 12 GB graphics card, about "+Gigabytes("standard")+" of models.";
        compactCard.Detail="For 8 GB graphics cards, about "+Gigabytes("compact")+" of models. Book voices sound the same.";
        standardCard.Bounds=new Rectangle(Edge,258,346,86); compactCard.Bounds=new Rectangle(Edge+362,258,346,86);
        standardCard.Chosen+=delegate { ChooseProfile("standard",true); }; compactCard.Chosen+=delegate { ChooseProfile("compact",true); };
        welcome.Controls.Add(standardCard); welcome.Controls.Add(compactCard);
        AddText(welcome,"Model files",Theme.Sans(9.5f),Theme.Muted,Edge,356,500,24);
        download.Detail="Setup downloads every model and checks each file.";
        local.Detail="Copy files you already have into a Local Models folder.";
        download.Bounds=new Rectangle(Edge,382,346,86); local.Bounds=new Rectangle(Edge+362,382,346,86);
        download.Chosen+=delegate { Choose(false); }; local.Chosen+=delegate { Choose(true); };
        welcome.Controls.Add(download); welcome.Controls.Add(local);
        note.Bounds=new Rectangle(Edge,476,Inner,44); note.ForeColor=Theme.Muted; note.Font=Theme.Sans(9.5f); welcome.Controls.Add(note);
        AddText(welcome,"Third-party components keep their own licenses: NVIDIA CUDA, FFmpeg (GPL), Qwen and Gemma (Apache-2.0). "+
                        "Your books and audio stay on this computer.",Theme.Sans(9),Theme.Muted,Edge,522,Inner,42);
        var licenses=new LinkLabel { Text="Licenses and details",Bounds=new Rectangle(Edge,583,200,28),LinkColor=Theme.Accent,
                                     ActiveLinkColor=Theme.Ink,BackColor=Color.Transparent,Font=Theme.Sans(9.5f) };
        licenses.LinkClicked+=delegate { ShowReadme(); };
        welcome.Controls.Add(licenses);
        var cancel=new Push("Cancel",false) { Bounds=new Rectangle(Width96-Edge-236-120,572,112,46) };
        cancel.Click+=delegate { Close(); };
        install.Bounds=new Rectangle(Width96-Edge-236,572,236,46);
        install.Click+=delegate { OnInstall(); };
        welcome.Controls.Add(cancel); welcome.Controls.Add(install);
        supplied=HasSuppliedModels(root);
        ChooseProfile(SuppliedProfile(root) ?? profile);
        Choose(supplied);
    }

    void BuildProgress() {
        progressTitle.Text="Installing AudioBook Studio"; progressTitle.Font=Theme.Serif(17); progressTitle.ForeColor=Theme.Ink;
        progressTitle.Bounds=new Rectangle(Edge,30,Inner,44); progress.Controls.Add(progressTitle);
        progressSubtitle.Text="Keep this window open. You can use your computer in the meantime.";
        progressSubtitle.Font=Theme.Sans(10); progressSubtitle.ForeColor=Theme.Muted; progressSubtitle.Bounds=new Rectangle(Edge,76,Inner,28);
        progress.Controls.Add(progressSubtitle);
        for(int i=0;i<Steps.Length;i++) {
            var row=new StepRow(Steps[i]) { Bounds=new Rectangle(Edge,120+i*42,Inner,38) };
            rows.Add(row); progress.Controls.Add(row);
        }
        activity.Bounds=new Rectangle(Edge,384,Inner,30); activity.Font=Theme.SansBold(10); activity.ForeColor=Theme.Ink;
        bar.Bounds=new Rectangle(Edge,420,Inner,8);
        amount.Bounds=new Rectangle(Edge,436,Inner,28); amount.Font=Theme.Sans(9.5f); amount.ForeColor=Theme.Muted;
        error.Bounds=new Rectangle(Edge,384,Inner,80); error.Font=Theme.Sans(10); error.ForeColor=Theme.Bad; error.Visible=false;
        progress.Controls.AddRange(new Control[] { activity,bar,amount,error });
        details.Text="Show details"; details.Bounds=new Rectangle(Edge,470,240,28); details.LinkColor=Theme.Accent;
        details.ActiveLinkColor=Theme.Ink; details.BackColor=Color.Transparent; details.Font=Theme.Sans(9.5f);
        details.LinkClicked+=delegate { log.Visible=!log.Visible; details.Text=log.Visible?"Hide details":"Show details"; };
        log.Multiline=true; log.ReadOnly=true; log.ScrollBars=ScrollBars.None; log.Font=new Font("Consolas",8.5f);
        log.BackColor=Theme.Surface; log.ForeColor=Theme.Muted; log.BorderStyle=BorderStyle.None; log.WordWrap=true;
        log.Bounds=new Rectangle(Edge,500,Inner,58); log.Visible=false;
        progress.Controls.Add(details); progress.Controls.Add(log);
        openFolder.Bounds=new Rectangle(Width96-Edge-3*136-24,572,136,46); retry.Bounds=new Rectangle(Width96-Edge-2*136-12,572,136,46);
        closeProgress.Bounds=new Rectangle(Width96-Edge-136,572,136,46);
        openFolder.Click+=delegate { Process.Start("explorer.exe",Quote(root)); };
        retry.Click+=delegate { BeginInstall(); };
        closeProgress.Click+=delegate { Close(); };
        progress.Controls.AddRange(new Control[] { openFolder,retry,closeProgress });
        openFolder.Visible=retry.Visible=closeProgress.Visible=false;
    }

    void BuildFinish() {
        int center=Width96/2;
        finish.Controls.Add(new BigCheck { Bounds=new Rectangle(center-36,56,72,72) });
        var title=AddText(finish,"AudioBook Studio is ready",Theme.Serif(19),Theme.Ink,0,148,Width96,46);
        title.TextAlign=ContentAlignment.MiddleCenter;
        var subtitle=AddText(finish,"Everything was installed and checked.",Theme.Sans(10.5f),Theme.Muted,0,198,Width96,30);
        subtitle.TextAlign=ContentAlignment.MiddleCenter;
        desktopShortcut.Bounds=new Rectangle(center-140,252,300,36); startShortcut.Bounds=new Rectangle(center-140,294,300,36);
        finish.Controls.Add(desktopShortcut); finish.Controls.Add(startShortcut);
        var open=new Push("Open AudioBook Studio",true) { Bounds=new Rectangle(center-136,360,272,50) };
        open.Click+=delegate { ApplyShortcuts(); OpenApplication(); Close(); };
        var close=new Push("Close",false) { Bounds=new Rectangle(center-136,424,272,46) };
        close.Click+=delegate { ApplyShortcuts(); Close(); };
        finish.Controls.Add(open); finish.Controls.Add(close);
        var hint=AddText(finish,"To remove it later, run Uninstall AudioBook Studio.exe in the installation folder.",
                         Theme.Sans(9),Theme.Muted,0,584,Width96,30);
        hint.TextAlign=ContentAlignment.MiddleCenter;
    }

    void ShowPage(Panel page) { foreach(var item in new[] { welcome,progress,finish }) item.Visible=item==page; }

    // -- welcome ----------------------------------------------------------------------------------------
    void ChooseProfile(string name,bool byUser=false) {
        if(name=="standard" && !standardCard.Enabled) return;
        profile=name; standardCard.Selected=name=="standard"; compactCard.Selected=name=="compact";
        // When the user switches, an instruction list setup wrote earlier is rewritten for this model set;
        // anything else in Local Models is left alone.
        if(byUser && Directory.Exists(Path.Combine(root,ModelsFolder))) {
            try { PrepareModelsFolder(root,profile); } catch(Exception) { }
        }
        ShowSpace();
        Choose(local.Selected);
    }

    // The model set whose audition model is already in Local Models, so a second run keeps the user's choice.
    static string SuppliedProfile(string folder) {
        foreach(string name in ((Dictionary<string,object>)Manifest()["profiles"]).Keys)
            if(File.Exists(Path.Combine(folder,ModelsFolder,(string)Profile(name)["voice_design"]))) return name;
        return null;
    }

    void ShowSpace() {
        if(freeBytes<0) return;
        long needed=Convert.ToInt64(Profile(profile)["min_free_gib"]);
        bool enough=freeBytes>=needed*1024L*1024*1024;
        space.Text=(freeBytes/(1024*1024*1024))+" GB free"+(enough?"":" ("+needed+" needed)");
        space.Fill=enough?Theme.OkSoft:Theme.BadSoft; space.ForeColor=enough?Theme.Ok:Theme.Bad; space.Invalidate();
    }

    void Choose(bool useLocal) {
        if(supplied) useLocal=true;
        download.Selected=!useLocal; local.Selected=useLocal; download.Enabled=!supplied;
        if(supplied) {
            note.Text="Model files were found in Local Models. Setup checks every file before using it. "+
                      "To download instead, remove them from that folder.";
            install.Text="Install";
        } else if(!useLocal) {
            note.Text="About "+Gigabytes(profile)+" is downloaded from Hugging Face and the Ollama registry, then checked.";
            install.Text="Install";
        } else if(!preparedFolder && !Directory.Exists(Path.Combine(root,ModelsFolder))) {
            note.Text="Setup creates a Local Models folder with a \""+Guide+"\" list of the exact files to copy. "+
                      "Nothing else is installed yet.";
            install.Text="Create Local Models folder";
        } else {
            note.Text="Copy the files listed in \""+Guide+"\" into Local Models, then choose Check again.";
            install.Text="Check again";
        }
    }

    void OnInstall() {
        if(!supplied && local.Selected) {
            if(install.Text=="Create Local Models folder") {
                try { Process.Start("explorer.exe",Quote(PrepareModelsFolder(root,profile))); preparedFolder=true; }
                catch(Exception failure) { MessageBox.Show(this,failure.Message,"Local Models",MessageBoxButtons.OK,MessageBoxIcon.Error); return; }
                Choose(true); return;
            }
            supplied=HasSuppliedModels(root);
            if(!supplied) { note.Text="No model files found in Local Models yet. Copy the listed files, then choose Check again."; return; }
            Choose(true); return;
        }
        ShowPage(progress);
        BeginInstall();
    }

    void CheckComputer() {
        try { freeBytes=new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace; ShowSpace(); }
        catch(Exception) { space.Text="Free space unknown"; space.Invalidate(); }
        var worker=new System.Threading.Thread(() => {
            string text; bool ok; double memory=-1;
            try {
                var info=new ProcessStartInfo("nvidia-smi","--query-gpu=name,compute_cap,memory.total,driver_version --format=csv,noheader,nounits") {
                    UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true };
                string[] parts;
                using(var smi=Process.Start(info)) { parts=smi.StandardOutput.ReadLine().Split(','); smi.WaitForExit(5000); }
                var invariant=System.Globalization.CultureInfo.InvariantCulture;
                double capability=double.Parse(parts[1].Trim(),invariant);
                memory=double.Parse(parts[2].Trim(),invariant);
                ok=SupportsGpu(capability,memory,parts[3].Trim());
                text=parts[0].Trim().Replace("NVIDIA ","")+" · "+Math.Round(memory/1024)+" GB"+(ok?"":" (not supported by this build)");
                if(!ok) memory=-1;
            } catch(Exception) { text="No supported NVIDIA graphics card found"; ok=false; }
            try {
                BeginInvoke((MethodInvoker)delegate {
                    gpu.Text=text; gpu.Fill=ok?Theme.OkSoft:Theme.WarnSoft; gpu.ForeColor=ok?Theme.Ok:Theme.Warn; gpu.Invalidate();
                    if(memory>=0 && memory<MinVram("standard")) {   // the card fits only the Compact set
                        standardCard.Enabled=false;
                        standardCard.Detail="Needs a 12 GB graphics card. This computer has "+Math.Round(memory/1024)+" GB.";
                        ChooseProfile("compact");
                    }
                });
            } catch(InvalidOperationException) { }  // the window was closed
        }) { IsBackground=true };
        worker.Start();
    }

    // -- installation ---------------------------------------------------------------------------------
    void BeginInstall() {
        foreach(var row in rows) row.State=StepState.Pending;
        current=-1; lastError=null; error.Visible=false; activity.Visible=bar.Visible=amount.Visible=true;
        openFolder.Visible=retry.Visible=closeProgress.Visible=false;
        progressTitle.Text="Installing AudioBook Studio";
        progressSubtitle.Text="Keep this window open. You can use your computer in the meantime.";
        Advance(0); Activity("Preparing setup",-1,"");
        animation.Start();
        try {
            if(session==null) {
                session=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AudioBookStudio-Installer","sessions",Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(session);
                foreach(string name in new string[]{"bootstrap.ps1","install.py","manifest.json","payload.zip"}) {
                    using(Stream source=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
                    using(var output=File.Create(Path.Combine(session,name))) source.CopyTo(output);
                }
            }
            string arguments="-NoProfile -ExecutionPolicy Bypass -File "+Quote(Path.Combine(session,"bootstrap.ps1"))+
                " -Target "+Quote(root)+" -InstallerPath "+Quote(Assembly.GetExecutingAssembly().Location)+
                " -Profile "+profile+" -AcceptLicenses";
            var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),arguments) {
                UseShellExecute=false, CreateNoWindow=true, RedirectStandardOutput=true, RedirectStandardError=true,
                StandardOutputEncoding=Encoding.UTF8, StandardErrorEncoding=Encoding.UTF8
            };
            var process=new Process { StartInfo=info, EnableRaisingEvents=true };
            process.OutputDataReceived+=delegate(object s,DataReceivedEventArgs a) { Received(a.Data); };
            process.ErrorDataReceived+=delegate(object s,DataReceivedEventArgs a) { Received(a.Data); };
            process.Exited+=delegate { process.WaitForExit(); int code=process.ExitCode; process.Dispose(); BeginInvoke((MethodInvoker)delegate { Finished(code); }); };
            running=true;
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
        } catch(Exception failure) { running=false; lastError=failure.Message; Finished(1); }
    }

    void Received(string line) {
        if(line==null) return;
        try { BeginInvoke((MethodInvoker)delegate { log.AppendText(line+Environment.NewLine); Interpret(line); }); }
        catch(InvalidOperationException) { }
    }

    // Maps the bootstrap's existing messages to the steps shown on screen.
    void Interpret(string line) {
        string text=line.Trim();
        if(text.StartsWith("ERROR:")) { lastError=text.Substring(6).Trim(); return; }
        Match progressLine=Regex.Match(text,@"^(\d+) / (\d+) MB$");
        if(progressLine.Success && currentFile!=null) { ShowBytes(long.Parse(progressLine.Groups[1].Value),long.Parse(progressLine.Groups[2].Value)); return; }
        if(text.StartsWith("Downloading portable Python")) { Advance(0); Activity("Downloading Python",-1,"About 46 MB"); }
        else if(text.StartsWith("Extracting Python")) { Advance(0); Activity("Unpacking Python",-1,""); }
        else if(text.StartsWith("Extracting the application")) { Advance(1); Activity("Unpacking the application",-1,""); }
        else if(text.StartsWith("Running:") && text.Contains("-m pip")) { Advance(1); Activity("Installing Python libraries",-1,"38 pinned packages"); }
        else if(text.StartsWith("Running:") && text.Contains("-m venv")) { Advance(1); Activity("Preparing the Python environment",-1,""); }
        else if(text.StartsWith("Installing portable FFmpeg")) { Advance(2); Activity("Installing FFmpeg",-1,""); }
        else if(text.StartsWith("Installing portable Ollama")) { Advance(2); Activity("Installing Ollama",-1,""); }
        else if(text.StartsWith("Preparing the pinned Gemma")) { Advance(4); Activity("Preparing the dialogue model",-1,""); }
        else if(text.StartsWith("Verifying the installation")) { Advance(5); Activity("Checking the installation",-1,"No audio is generated"); }
        else if(text.StartsWith("Downloading: ")) {
            string name=text.Substring(13); currentFile=name; fileStartBytes=-1;
            if(name.StartsWith("qwen-")) Advance(3);
            Activity("Downloading "+Friendly(name),-1,"Starting…");
        } else if(text.StartsWith("Checking local model: ")) {
            Advance(3); currentFile=null; Activity("Checking and copying "+Friendly(text.Substring(22)),-1,"Large files take a few minutes");
        } else if(text.StartsWith("Checking SHA-256: ")) {
            string name=text.Substring(18); currentFile=null;
            if(name.StartsWith("qwen-")) Advance(3);
            Activity("Checking "+Friendly(name),-1,"");
        }
    }

    static string Friendly(string name) {
        string lower=name.ToLowerInvariant();
        if(lower.Contains("voicedesign")) return "the Voice Design model";
        if(lower.Contains("customvoice")) return "the CustomVoice model";
        if(lower.Contains("base")) return "the voice cloning model";
        if(lower.Contains("tokenizer")) return "the audio codec";
        if(lower.StartsWith("sha256-")) return "the dialogue model";
        if(lower.Contains("ffmpeg")) return "FFmpeg";
        if(lower.Contains("ollama")) return "Ollama";
        return name;
    }

    void Advance(int step) {
        if(step<current) return;
        for(int i=0;i<rows.Count;i++) rows[i].State=i<step?StepState.Done:(i==step?StepState.Active:StepState.Pending);
        current=step;
    }

    void Activity(string text,float value,string detail) { activity.Text=text; bar.Value=value; bar.Invalidate(); amount.Text=detail; }

    void ShowBytes(long received,long total) {
        bar.Value=total>0?received/(float)total:-1; bar.Invalidate();
        string detail=Megabytes(received)+" of "+Megabytes(total);
        if(fileStartBytes<0) { fileStartBytes=received; fileStart=DateTime.UtcNow; }
        double seconds=(DateTime.UtcNow-fileStart).TotalSeconds;
        if(seconds>5 && received>fileStartBytes) {
            double remaining=(total-received)/((received-fileStartBytes)/seconds);
            detail+=" · "+(remaining<90?"less than 2 minutes left":"about "+Math.Round(remaining/60)+" minutes left");
        }
        amount.Text=detail;
    }

    static string Megabytes(long value) { return value>=1024?(value/1024.0).ToString("0.0")+" GB":value+" MB"; }

    void Finished(int code) {
        running=false; animation.Stop();
        if(code==0) {
            foreach(var row in rows) row.State=StepState.Done;
            RemoveSession();
            ShowPage(finish);
            return;
        }
        if(current>=0) rows[current].State=StepState.Failed;
        progressTitle.Text="Setup could not finish";
        progressSubtitle.Text="Completed steps are kept and reused when you retry.";
        activity.Visible=bar.Visible=amount.Visible=false;
        error.Text=(lastError ?? "Setup stopped unexpectedly.")+"\nSolve this, then choose Retry. Details are also in install.log in the installation folder.";
        error.Visible=true; openFolder.Visible=retry.Visible=closeProgress.Visible=true;
        if(!log.Visible) { log.Visible=true; details.Text="Hide details"; }
        log.SelectionStart=log.TextLength; log.ScrollToCaret();
    }

    void RemoveSession() {
        if(session==null) return;
        string parent=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"AudioBookStudio-Installer","sessions")+Path.DirectorySeparatorChar;
        if(Path.GetFullPath(session).StartsWith(parent,StringComparison.OrdinalIgnoreCase) && Directory.Exists(session)) {
            try { Directory.Delete(session,true); session=null; } catch(IOException) { } catch(UnauthorizedAccessException) { }
        }
    }

    // -- finish -----------------------------------------------------------------------------------------
    void ApplyShortcuts() {
        try {
            CreateShortcuts(root,desktopShortcut.Checked?Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory):"",
                            startShortcut.Checked?Environment.GetFolderPath(Environment.SpecialFolder.Programs):"");
        } catch(Exception failure) { MessageBox.Show(this,"Could not create a shortcut: "+failure.Message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Warning); }
    }

    void OpenApplication() {
        try { Process.Start(new ProcessStartInfo(Path.Combine(root,"AudioBook Studio.exe")) { WorkingDirectory=root,UseShellExecute=true }); }
        catch(Exception failure) { MessageBox.Show(this,failure.Message,"AudioBook Studio",MessageBoxButtons.OK,MessageBoxIcon.Error); }
    }

    // Shortcuts to the launcher. Each one is recorded in shortcuts.txt, so the uninstaller removes exactly these.
    static void CreateShortcuts(string folder,string desktop,string programs) {
        string target=Path.Combine(folder,"AudioBook Studio.exe");
        var created=new List<string>();
        foreach(string directory in new[] { desktop,programs }) {
            if(string.IsNullOrEmpty(directory)) continue;
            Directory.CreateDirectory(directory);
            string link=Path.Combine(directory,"AudioBook Studio.lnk");
            if(File.Exists(link) && !string.Equals(LinkTarget(link),target,StringComparison.OrdinalIgnoreCase))
                link=Path.Combine(directory,"AudioBook Studio ("+Path.GetFileName(folder)+").lnk");
            WriteLink(link,target,folder);
            created.Add(link);
        }
        if(created.Count>0) File.AppendAllLines(Path.Combine(folder,"shortcuts.txt"),created,new UTF8Encoding(false));
    }

    static void WriteLink(string link,string target,string folder) {
        object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        try {
            object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[] { link });
            try {
                Type type=shortcut.GetType();
                type.InvokeMember("TargetPath",BindingFlags.SetProperty,null,shortcut,new object[] { target });
                type.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,shortcut,new object[] { folder });
                type.InvokeMember("IconLocation",BindingFlags.SetProperty,null,shortcut,new object[] { target+",0" });
                type.InvokeMember("Description",BindingFlags.SetProperty,null,shortcut,new object[] { "AudioBook Studio" });
                type.InvokeMember("Save",BindingFlags.InvokeMethod,null,shortcut,null);
            } finally { Marshal.ReleaseComObject(shortcut); }
        } finally { Marshal.ReleaseComObject(shell); }
    }

    static string LinkTarget(string link) {
        object shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
        try {
            object shortcut=shell.GetType().InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[] { link });
            try { return (string)shortcut.GetType().InvokeMember("TargetPath",BindingFlags.GetProperty,null,shortcut,null); }
            finally { Marshal.ReleaseComObject(shortcut); }
        } finally { Marshal.ReleaseComObject(shell); }
    }

    // -- shared helpers -----------------------------------------------------------------------------
    static string Quote(string value) { return "\""+value.Replace("\"","")+"\""; }

    static byte[] IconBytes() {
        using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("app.ico"))
        using(var copy=new MemoryStream()) { stream.CopyTo(copy); return copy.ToArray(); }
    }

    static Icon AppIcon() { using(var stream=new MemoryStream(IconBytes())) return new Icon(stream,32,32); }

    // The largest frame of the ICO is a PNG; .NET Framework cannot turn PNG icon frames into bitmaps itself.
    static Image Logo() {
        byte[] ico=IconBytes();
        int count=BitConverter.ToUInt16(ico,4), best=-1, bestSize=0;
        for(int i=0;i<count;i++) {
            int size=ico[6+16*i]==0?256:ico[6+16*i];
            if(size>bestSize) { bestSize=size; best=i; }
        }
        int length=BitConverter.ToInt32(ico,6+16*best+8), offset=BitConverter.ToInt32(ico,6+16*best+12);
        return Image.FromStream(new MemoryStream(ico,offset,length));
    }

    void ShowReadme() {
        using(var window=new Form { Text="Licenses and installation",Size=new Size((int)(820*Theme.K),(int)(650*Theme.K)),
                                    StartPosition=FormStartPosition.CenterParent,BackColor=Theme.Surface,Icon=AppIcon() }) {
            var text=new TextBox { Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,Font=Theme.Sans(10),
                                   BackColor=Theme.Surface,ForeColor=Theme.Ink,BorderStyle=BorderStyle.None };
            using(var reader=new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("README.md"),Encoding.UTF8))
                text.Text=reader.ReadToEnd().Replace("\n","\r\n");
            window.Controls.Add(text); window.ShowDialog(this);
        }
    }

    // A folder holding only the instruction file means "no models supplied": setup downloads them.
    static bool HasSuppliedModels(string folder) {
        string models=Path.Combine(folder,ModelsFolder);
        return Directory.Exists(models) && Directory.EnumerateFiles(models,"*",SearchOption.AllDirectories)
            .Any(file => !Path.GetFileName(file).Equals(Guide,StringComparison.OrdinalIgnoreCase));
    }

    // Creates Local Models (and ollama\blobs) with the exact list of files to copy for one model set. User files are
    // never overwritten; only an instruction list that setup itself wrote is updated for another model set.
    static string PrepareModelsFolder(string folder,string name) {
        string models=Path.Combine(Path.GetFullPath(folder),ModelsFolder);
        Directory.CreateDirectory(Path.Combine(models,"ollama","blobs"));
        string guide=Path.Combine(models,Guide), text=GuideText(name);
        if(!File.Exists(guide)) File.WriteAllText(guide,text,new UTF8Encoding(false));
        else {
            string existing=File.ReadAllText(guide,Encoding.UTF8);
            if(existing.StartsWith(GuideHeader) && existing!=text) File.WriteAllText(guide,text,new UTF8Encoding(false));
        }
        return models;
    }

    static string GuideText(string name) {
        var profile=Profile(name);
        string[] files=ProfileFiles(name);
        string tag=(string)profile["gemma"], repository=tag.Split(':')[0];
        object[] blobs=GemmaBlobs(name);
        var text=new StringBuilder();
        text.Append(GuideHeader+"\r\n\r\n"+
                    "Model set: "+profile["label"]+". Choose the same model set in setup.\r\n\r\n"+
                    "Run AudioBookStudio-Setup-1.0.0.exe again after copying them. Setup checks the size and SHA-256 of every\r\n"+
                    "file and copies them into the installation; the files you place here are left unchanged.\r\n"+
                    "All files below are needed. If one is missing or different, setup stops and explains which one.\r\n"+
                    "To let setup download everything instead, leave only this file here (or delete the folder).\r\n\r\n"+
                    "1. Qwen TTS models - put these "+files.Length+" files directly in this folder, with exactly these names:\r\n\r\n");
        foreach(Dictionary<string,object> item in (object[])Manifest()["models"]) {
            if(!files.Contains((string)item["name"])) continue;
            text.Append("   "+item["name"]+"   ("+Convert.ToInt64(item["size"]).ToString("N0")+" bytes)\r\n"+
                        "      SHA-256 "+item["sha256"]+"\r\n      "+item["url"]+"\r\n\r\n");
        }
        text.Append("2. Gemma dialogue model - put these "+blobs.Length+" files in the subfolder ollama\\blobs, with exactly these names.\r\n"+
                    "   If you already use Ollama with "+tag+", they are usually in %USERPROFILE%\\.ollama\\models\\blobs.\r\n\r\n");
        foreach(Dictionary<string,object> item in blobs) {
            string digest=(string)item["digest"];
            text.Append("   ollama\\blobs\\"+digest.Replace(':','-')+"   ("+Convert.ToInt64(item["size"]).ToString("N0")+" bytes)\r\n"+
                        "      https://registry.ollama.ai/v2/library/"+repository+"/blobs/"+digest+"\r\n\r\n");
        }
        return text.ToString();
    }

    // -- model sets (manifest.json "profiles") -----------------------------------------------------------
    static Dictionary<string,object> Manifest() {
        if(manifestCache==null) {
            string json;
            using(var reader=new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("manifest.json"),Encoding.UTF8))
                json=reader.ReadToEnd();
            manifestCache=(Dictionary<string,object>)new JavaScriptSerializer { MaxJsonLength=int.MaxValue }.DeserializeObject(json);
        }
        return manifestCache;
    }

    static string DefaultProfile() { return (string)Manifest()["default_profile"]; }
    static Dictionary<string,object> Hardware() { return (Dictionary<string,object>)Manifest()["hardware"]; }
    internal static bool SupportsGpu(double capability,double memory,string driver) {
        return ((object[])Hardware()["cuda_architectures"]).Any(value => Convert.ToDouble(value)/10==capability) &&
               memory>=MinVram("compact") &&
               new Version(driver)>=new Version((string)Hardware()["min_driver"]);
    }
    static Dictionary<string,object> Profile(string name) { return (Dictionary<string,object>)((Dictionary<string,object>)Manifest()["profiles"])[name]; }
    static double MinVram(string name) { return Convert.ToDouble(Profile(name)["min_vram_mb"]); }
    static string[] ProfileFiles(string name) { var profile=Profile(name); return ProfileKeys.Select(key => (string)profile[key]).Distinct().ToArray(); }

    static object[] GemmaBlobs(string name) {
        var models=(Dictionary<string,object>)Manifest()["gemma_models"];
        return (object[])((Dictionary<string,object>)models[(string)Profile(name)["gemma"]])["blobs"];
    }

    static string Gigabytes(string name) {
        string[] files=ProfileFiles(name); long total=0;
        foreach(Dictionary<string,object> item in (object[])Manifest()["models"])
            if(files.Contains((string)item["name"])) total+=Convert.ToInt64(item["size"]);
        foreach(Dictionary<string,object> item in GemmaBlobs(name)) total+=Convert.ToInt64(item["size"]);
        return Math.Round(total/(1024.0*1024*1024)).ToString("0")+" GB";
    }

    // Developer aid: renders each page with sample states to PNG files, without installing anything.
    static void RenderPreview(string output) {
        Directory.CreateDirectory(output);
        using(var form=new Setup(@"D:\AudioBook Studio") { Opacity=0,ShowInTaskbar=false,Preview=true }) {
            form.Show();
            form.gpu.Text="GeForce RTX 4080 Laptop GPU · 12 GB"; form.gpu.Fill=Theme.OkSoft; form.gpu.ForeColor=Theme.Ok;
            form.space.Text="473 GB free"; form.space.Fill=Theme.OkSoft; form.space.ForeColor=Theme.Ok;
            form.supplied=false; form.Choose(false); Save(form.welcome,output,"1-welcome-download.png");
            form.Choose(true); Save(form.welcome,output,"2-welcome-local.png");
            form.supplied=true; form.Choose(true); Save(form.welcome,output,"3-welcome-models-found.png");
            form.supplied=false; form.Choose(false);
            form.gpu.Text="GeForce RTX 4060 Laptop GPU · 8 GB";
            form.standardCard.Enabled=false; form.standardCard.Detail="Needs a 12 GB graphics card. This computer has 8 GB.";
            form.ChooseProfile("compact"); Save(form.welcome,output,"3b-welcome-compact.png");
            form.ShowPage(form.progress);
            form.Advance(3); form.currentFile="qwen-talker-1.7b-voicedesign-F32.gguf";
            form.Activity("Downloading the Voice Design model",-1,"");
            form.ShowBytes(3277,7317); form.amount.Text="3.2 GB of 7.1 GB · about 6 minutes left";
            Save(form.progress,output,"4-progress.png");
            form.log.AppendText("Using models in the Local Models subfolder. All files will be verified.\r\nChecking local model: qwen-talker-1.7b-voicedesign-F32.gguf\r\n");
            form.lastError="A different file already exists at the destination: models\\qwen-talker-1.7b-voicedesign-F32.gguf";
            form.Finished(1); Save(form.progress,output,"5-error.png");
            form.ShowPage(form.finish); Save(form.finish,output,"6-finish.png");
        }
    }

    static void Save(Control page,string output,string name) {
        Application.DoEvents();
        using(var image=new Bitmap(page.Width,page.Height)) {
            page.DrawToBitmap(image,new Rectangle(0,0,page.Width,page.Height));
            image.Save(Path.Combine(output,name),ImageFormat.Png);
        }
    }
}

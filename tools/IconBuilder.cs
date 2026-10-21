// Reproduce the existing web brand-mark, including its five SVG strokes and dark-mode gradient.
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

class IconBuilder {
    static void Main(string[] args) {
        string folder = args[0]; Directory.CreateDirectory(folder);
        using(var master = new Bitmap(1024,1024,PixelFormat.Format32bppArgb)) {
            using(var graphics=Graphics.FromImage(master)) {
                graphics.SmoothingMode=SmoothingMode.AntiAlias;
                graphics.ScaleTransform(2,2);
                var bounds=new RectangleF(12,12,488,488);
                float radius=141,diameter=radius*2;
                using(var shape=new GraphicsPath()) {
                    shape.AddArc(bounds.X,bounds.Y,diameter,diameter,180,90);
                    shape.AddArc(bounds.Right-diameter,bounds.Y,diameter,diameter,270,90);
                    shape.AddArc(bounds.Right-diameter,bounds.Bottom-diameter,diameter,diameter,0,90);
                    shape.AddArc(bounds.X,bounds.Bottom-diameter,diameter,diameter,90,90);
                    shape.CloseFigure();
                    using(var gradient=new LinearGradientBrush(bounds,ColorTranslator.FromHtml("#e27a4b"),ColorTranslator.FromHtml("#7a3417"),50f))
                        graphics.FillPath(gradient,shape);
                }
                // Original viewBox 0 0 24 24: M5 9v6 M9 6v12 M13 10v4 M17 7v10 M21 11v2.
                float scale=488f*22/38/24, offset=(512-24*scale)/2;
                int[,] bars={{5,9,15},{9,6,18},{13,10,14},{17,7,17},{21,11,13}};
                using(var pen=new Pen(Color.White,2.2f*scale)) {
                    pen.StartCap=LineCap.Round; pen.EndCap=LineCap.Round;
                    for(int index=0;index<5;index++)
                        graphics.DrawLine(pen,offset+bars[index,0]*scale,offset+bars[index,1]*scale,
                                          offset+bars[index,0]*scale,offset+bars[index,2]*scale);
                }
            }
            int[] sizes={16,24,32,48,64,128,256};
            byte[][] frames=new byte[sizes.Length][];
            for(int index=0;index<sizes.Length;index++) frames[index]=Png(master,sizes[index]);
            File.WriteAllBytes(Path.Combine(folder,"audiobook.png"),Png(master,512));
            using(var writer=new BinaryWriter(File.Create(Path.Combine(folder,"audiobook.ico")))) {
                writer.Write((ushort)0); writer.Write((ushort)1); writer.Write((ushort)sizes.Length);
                uint offset=(uint)(6+16*sizes.Length);
                for(int index=0;index<sizes.Length;index++) {
                    writer.Write((byte)(sizes[index]==256?0:sizes[index]));
                    writer.Write((byte)(sizes[index]==256?0:sizes[index]));
                    writer.Write((byte)0);writer.Write((byte)0);writer.Write((ushort)1);writer.Write((ushort)32);
                    writer.Write((uint)frames[index].Length);writer.Write(offset);
                    offset+=(uint)frames[index].Length;
                }
                foreach(byte[] frame in frames) writer.Write(frame);
            }
        }
    }
    static byte[] Png(Bitmap original,int size) {
        using(var image=new Bitmap(size,size,PixelFormat.Format32bppArgb))
        using(var graphics=Graphics.FromImage(image))
        using(var stream=new MemoryStream()) {
            graphics.InterpolationMode=InterpolationMode.HighQualityBicubic;
            graphics.CompositingQuality=CompositingQuality.HighQuality;
            graphics.PixelOffsetMode=PixelOffsetMode.HighQuality;
            graphics.DrawImage(original,new Rectangle(0,0,size,size));
            image.Save(stream,ImageFormat.Png);return stream.ToArray();
        }
    }
}

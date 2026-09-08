// Session-scoped privileged broker. No output files, child commands, or paths
// originate from clients. Recipe and artifact bytes are pinned before listening.
using System;
using System.IO;
using System.Text;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Threading;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

public static class WindowsRestartBroker {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength=134217728, RecursionLimit=32 };
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false,true);
    static readonly Dictionary<string,Record> Records = new Dictionary<string,Record>(StringComparer.Ordinal);
    static readonly List<object> Retained = new List<object>();
    static byte[] secret; static Recipe recipe; static bool poisoned,stopping;
    const int MaximumRecipe=134217728;
    sealed class Record { public string Op; public int Disk; public Dictionary<string,object> Receipt; public string Response; }
    sealed class Region { public int Offset; public byte[] Data; public string Hash; }
    sealed class Recipe {
        public Dictionary<string,object> Raw; public byte[] Firmware,Mbr,Directory; public Region[] Regions;
        public long DiskBytes,PartitionOffset,DiskDirectoryOffset,VolumeOffset;
        public int DirectoryOffset,PayloadOffset,PayloadBytes;public string PayloadHash; public string Serial,UsbSerial,VolumeSerial,PlanHash,PlanPath,BuildId,FirmwareHash;
    }
    static Dictionary<string,object> D(params object[] pairs) { var d=new Dictionary<string,object>(); for(int i=0;i<pairs.Length;i+=2)d.Add((string)pairs[i],pairs[i+1]); return d; }
    static string Canonical(object value) {
        var dictionary=value as Dictionary<string,object>;
        if(dictionary!=null){var keys=new List<string>(dictionary.Keys);keys.Sort(StringComparer.Ordinal);var text=new StringBuilder("{");bool first=true;foreach(string key in keys){if(!first)text.Append(',');first=false;text.Append(Json.Serialize(key));text.Append(':');text.Append(Canonical(dictionary[key]));}return text.Append('}').ToString();}
        var list=value as IEnumerable;if(list!=null&&!(value is string)){var text=new StringBuilder("[");bool first=true;foreach(object item in list){if(!first)text.Append(',');first=false;text.Append(Canonical(item));}return text.Append(']').ToString();}return Json.Serialize(value);
    }
    static string Now() { return DateTime.UtcNow.ToString("o"); }
    static Dictionary<string,object> Object(object value) { var d=value as Dictionary<string,object>; if(d==null)throw new InvalidDataException("Expected object"); return d; }
    static object Required(Dictionary<string,object>d,string k) { object v;if(!d.TryGetValue(k,out v)||v==null)throw new InvalidDataException("Missing "+k);return v; }
    static string Text(Dictionary<string,object>d,string k) { var s=Required(d,k) as string;if(s==null)throw new InvalidDataException("Invalid "+k);return s; }
    static long Number(Dictionary<string,object>d,string k) { object v=Required(d,k);if(!(v is int)&&!(v is long))throw new InvalidDataException("Invalid integer "+k);return Convert.ToInt64(v); }
    static bool Hex(string s,int n) { if(s==null||s.Length!=n)return false;foreach(char c in s)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')||(c>='A'&&c<='F')))return false;return true; }
    static string Hash(byte[] b) { using(var sha=SHA256.Create()){var h=sha.ComputeHash(b);return BitConverter.ToString(h).Replace("-","").ToLowerInvariant();} }
    static byte[] DecodeHash(string s) { if(!Hex(s,64))throw new InvalidDataException("Invalid hash/token");byte[] b=new byte[32];for(int i=0;i<32;i++)b[i]=Convert.ToByte(s.Substring(i*2,2),16);return b; }
    static bool Equal(byte[] a,byte[] b) { if(a.Length!=b.Length)return false;int diff=0;for(int i=0;i<a.Length;i++)diff|=a[i]^b[i];return diff==0; }
    static bool SliceEqual(byte[] whole,int start,byte[] b) { int diff=0;for(int i=0;i<b.Length;i++)diff|=whole[start+i]^b[i];return diff==0; }
    static bool Zero(byte[] b,int offset,int count) { int v=0;for(int i=0;i<count;i++)v|=b[offset+i];return v==0; }
    static byte[] Artifact(Dictionary<string,object>d,string b64,string hash,int max) { string s=Text(d,b64);if(s.Length>(long)max*4/3+8)throw new InvalidDataException("Artifact too large");byte[] b=Convert.FromBase64String(s);if(b.Length>max||Hash(b)!=Text(d,hash).ToLowerInvariant())throw new InvalidDataException("Artifact hash mismatch: "+b64);return b; }
    static string Absolute(string s) { if(!Path.IsPathRooted(s)||!String.Equals(Path.GetFullPath(s),s,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Absolute canonical path required");return s; }
    static Recipe Load(string path,string expected) {
        byte[] bytes;
        using(var f=new FileStream(Absolute(path),FileMode.Open,FileAccess.Read,FileShare.Read)) {
            if(f.Length<2||f.Length>MaximumRecipe)throw new InvalidDataException("Recipe size");bytes=new byte[(int)f.Length];int n=0;while(n<bytes.Length){int got=f.Read(bytes,n,bytes.Length-n);if(got==0)throw new EndOfStreamException();n+=got;}
        }
        if(!Hex(expected,64)||Hash(bytes)!=expected.ToLowerInvariant())throw new InvalidDataException("Recipe SHA256 mismatch");
        var d=Object(Json.DeserializeObject(Utf8.GetString(bytes)));var r=new Recipe();r.Raw=d;
        r.Firmware=Artifact(d,"firmware_base64","firmware_sha256",67108864);r.FirmwareHash=Hash(r.Firmware);
        r.Mbr=Artifact(d,"mbr_base64","mbr_sha256",512);r.Directory=Artifact(d,"directory_base64","directory_sha256",512);
        r.DirectoryOffset=checked((int)Number(d,"directory_offset"));r.DiskDirectoryOffset=Number(d,"disk_directory_offset");r.PartitionOffset=Number(d,"partition_offset");r.DiskBytes=Number(d,"disk_bytes");r.VolumeOffset=Number(d,"volume_partition_offset");
        if(r.Mbr.Length!=512||r.Directory.Length!=512||r.Mbr[510]!=0x55||r.Mbr[511]!=0xaa||r.Firmware.Length%512!=0||r.Firmware.Length==0||r.DirectoryOffset!=16896||r.DiskDirectoryOffset!=49152||r.PartitionOffset!=32256||r.DiskBytes!=64021856256L||r.VolumeOffset!=41126400||r.DirectoryOffset+512>r.Firmware.Length||r.PartitionOffset+r.Firmware.Length>r.VolumeOffset||r.PartitionOffset+r.DirectoryOffset!=r.DiskDirectoryOffset)throw new InvalidDataException("Recipe geometry rejected");
        r.Serial=Text(d,"serial");r.UsbSerial=Text(d,"usbserial");r.VolumeSerial=Text(d,"volume_serial").ToUpperInvariant();r.PlanHash=Text(d,"plan_sha256").ToLowerInvariant();r.PlanPath=Absolute(Text(d,"plan_path"));r.BuildId=Text(d,"boot_build_id");
        if(r.Serial.Length<1||r.Serial.Length>64||r.Serial.Trim()!=r.Serial||r.UsbSerial.Length<1||r.UsbSerial.Length>128||!Hex(r.VolumeSerial,8)||!Hex(r.PlanHash,64)||!Hex(r.BuildId,64))throw new InvalidDataException("Recipe identity rejected");
        var values=Required(d,"regions") as object[];if(values==null||values.Length<1||values.Length>32)throw new InvalidDataException("Region count");r.Regions=new Region[values.Length];
        for(int i=0;i<values.Length;i++) {
            var entry=Object(values[i]);var region=new Region();region.Offset=checked((int)Number(entry,"offset"));region.Data=Artifact(entry,"data_base64","sha256",8388608);region.Hash=Hash(region.Data);
            if(region.Offset<0||region.Offset%512!=0||region.Data.Length==0||region.Data.Length%512!=0||(long)region.Offset+region.Data.Length>r.Firmware.Length||((long)region.Offset<r.DirectoryOffset+512&&r.DirectoryOffset<(long)region.Offset+region.Data.Length)||!Zero(r.Firmware,region.Offset,region.Data.Length))throw new InvalidDataException("Invalid region bounds/original bytes");
            for(int j=0;j<i;j++)if(region.Offset<(long)r.Regions[j].Offset+r.Regions[j].Data.Length&&r.Regions[j].Offset<(long)region.Offset+region.Data.Length)throw new InvalidDataException("Overlapping regions");r.Regions[i]=region;
        }
        int payload=checked((int)Number(d,"original_payload_offset")),length=checked((int)Number(d,"original_payload_bytes"));
        if(payload<0||length<=0||(long)payload+length>r.Firmware.Length)throw new InvalidDataException("Original payload bounds");byte[] original=new byte[length];Buffer.BlockCopy(r.Firmware,payload,original,0,length);if(Hash(original)!=Text(d,"original_payload_sha256").ToLowerInvariant())throw new InvalidDataException("Original payload hash");r.PayloadOffset=payload;r.PayloadBytes=length;r.PayloadHash=Hash(original);
        // Large serialized strings no longer needed; only pinned decoded bytes remain.
        r.Raw=null;return r;
    }
    // Constant script. Client data is never inserted into PowerShell source.
    const string IdentityScript=@"
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$items=@();
foreach($d in @(Get-Disk | Where-Object {$_.FriendlyName -eq 'Apple iPod' -and [string]$_.BusType -eq 'USB'})) {
 $raw=Get-CimInstance Win32_DiskDrive -Filter (""Index=""+[int]$d.Number);
 $vols=@();foreach($p in @(Get-Partition -DiskNumber $d.Number | Where-Object {$_.DriveLetter})) {
  $letter=[string]$p.DriveLetter;if($letter -notmatch '^[A-Za-z]$'){throw 'Invalid drive letter'};
  $v=Get-Volume -Partition $p;$logical=Get-CimInstance Win32_LogicalDisk -Filter (""DeviceID='""+$letter+"":'"");
  $vols+=@{Drive=$letter.ToUpper();Offset=[long]$p.Offset;Size=[long]$p.Size;PartitionNumber=$p.PartitionNumber;UniqueId=[string]$v.UniqueId;FileSystem=[string]$v.FileSystemType;Serial=[string]$logical.VolumeSerialNumber}
 }
 $items+=@{Number=$d.Number;PnpId=[string]$raw.PNPDeviceID;FriendlyName=[string]$d.FriendlyName;SerialNumber=[string]$d.SerialNumber;Size=[long]$d.Size;BusType=[string]$d.BusType;LogicalSectorSize=$d.LogicalSectorSize;UniqueId=[string]$d.UniqueId;IsBoot=[bool]$d.IsBoot;IsSystem=[bool]$d.IsSystem;IsOffline=[bool]$d.IsOffline;IsReadOnly=[bool]$d.IsReadOnly;Volumes=$vols}
};@{Disks=$items}|ConvertTo-Json -Depth 6 -Compress";
    static Dictionary<string,object> Identity(int disk) {
        string exe=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),@"WindowsPowerShell\v1.0\powershell.exe");
        var info=new ProcessStartInfo(exe,"-NoLogo -NoProfile -NonInteractive -EncodedCommand "+Convert.ToBase64String(Encoding.Unicode.GetBytes(IdentityScript))){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
        string system=Environment.GetFolderPath(Environment.SpecialFolder.System);
        info.EnvironmentVariables["PSModulePath"]=Path.Combine(system,@"WindowsPowerShell\v1.0\Modules");
        info.EnvironmentVariables["PATH"]=system+";"+Directory.GetParent(system).FullName;
        info.EnvironmentVariables.Remove("PSModuleAnalysisCachePath");
        info.WorkingDirectory=AppDomain.CurrentDomain.BaseDirectory;
        var output=new StringBuilder();var error=new StringBuilder();
        using(var p=new Process()){p.StartInfo=info;
            p.OutputDataReceived+=(s,e)=>{if(e.Data!=null)lock(output){if(output.Length<1048576)output.AppendLine(e.Data);}};
            p.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)lock(error){if(error.Length<8192)error.AppendLine(e.Data);}};
            if(!p.Start())throw new IOException("Cannot launch identity query");p.BeginOutputReadLine();p.BeginErrorReadLine();
            if(!p.WaitForExit(15000)){try{p.Kill();}catch{}throw new TimeoutException("Identity query timeout");}p.WaitForExit();
            if(p.ExitCode!=0)throw new IOException("Identity query rejected: "+error.ToString());
        }
        var root=Object(Json.DeserializeObject(output.ToString()));var disks=Required(root,"Disks") as object[];if(disks==null)throw new InvalidDataException("Disk query shape");
        Dictionary<string,object> match=null;int serialMatches=0;
        foreach(var o in disks){var d=Object(o);if(Text(d,"SerialNumber").Trim()==recipe.Serial){serialMatches++;match=d;}}
        if(serialMatches!=1||Number(match,"Number")!=disk||Number(match,"Size")!=recipe.DiskBytes||Number(match,"LogicalSectorSize")!=512||Text(match,"BusType")!="USB"||Text(match,"FriendlyName")!="Apple iPod"||!Required(match,"IsBoot").Equals(false)||!Required(match,"IsSystem").Equals(false)||!Required(match,"IsOffline").Equals(false)||!Required(match,"IsReadOnly").Equals(false)||Text(match,"UniqueId").Length==0)throw new InvalidDataException("Disk identity rejected");
        string pnp=Text(match,"PnpId").ToUpperInvariant();string[] components=pnp.Split('\\');
        if(components.Length!=3||components[0]!="USBSTOR"||!components[1].StartsWith("DISK&VEN_APPLE&PROD_IPOD&",StringComparison.Ordinal)||components[2]!=recipe.UsbSerial.ToUpperInvariant()+"&0")throw new InvalidDataException("USB PNP serial rejected");
        var vols=Required(match,"Volumes") as object[];if(vols==null||vols.Length!=1)throw new InvalidDataException("Expected one mounted volume");var v=Object(vols[0]);
        if(Number(v,"Offset")!=recipe.VolumeOffset||Number(v,"Size")<=0||Number(v,"Size")>recipe.DiskBytes-recipe.VolumeOffset||Text(v,"FileSystem")!="FAT32"||Text(v,"Serial").ToUpperInvariant()!=recipe.VolumeSerial||Text(v,"UniqueId").Length==0)throw new InvalidDataException("Volume identity rejected");return match;
    }
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] static extern SafeFileHandle CreateFile(string name,uint access,uint share,IntPtr security,uint creation,uint flags,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool CancelIoEx(SafeFileHandle handle,IntPtr overlapped);
    sealed class Device:IDisposable {
        SafeFileHandle handle;FileStream stream;bool retained;
        public Device(int disk) {handle=CreateFile(@"\\.\PhysicalDrive"+disk,0xc0000000,3,IntPtr.Zero,3,0xc0000000,IntPtr.Zero);if(handle.IsInvalid)throw new IOException("Raw device open failed: "+Marshal.GetLastWin32Error());stream=new FileStream(handle,FileAccess.ReadWrite,1,true);}
        void Wait(IAsyncResult result) {
            if(result.AsyncWaitHandle.WaitOne(10000))return;
            poisoned=true;CancelIoEx(handle,IntPtr.Zero);
            if(!result.AsyncWaitHandle.WaitOne(2000)){retained=true;Retained.Add(this);Retained.Add(result);}
            throw new TimeoutException("Device I/O timeout; session poisoned, no replay");
        }
        public byte[] Read(long offset,int count){var b=new byte[count];stream.Position=offset;int n=0;
            while(n<count){var result=stream.BeginRead(b,n,count-n,null,null);Wait(result);int got=stream.EndRead(result);result.AsyncWaitHandle.Close();if(got<=0)throw new EndOfStreamException("Short raw read");n+=got;}return b;}
        public void Write(long offset,byte[] bytes){stream.Position=offset;var result=stream.BeginWrite(bytes,0,bytes.Length,null,null);Wait(result);stream.EndWrite(result);result.AsyncWaitHandle.Close();}
        public void Flush(){Exception failure=null;var done=new ManualResetEvent(false);var t=new Thread(()=>{try{stream.Flush(true);}catch(Exception e){failure=e;}finally{done.Set();}});t.IsBackground=true;t.Start();
            if(!done.WaitOne(10000)){poisoned=true;retained=true;Retained.Add(this);Retained.Add(done);throw new TimeoutException("Device flush timeout; session poisoned, no replay");}done.Close();if(failure!=null)throw failure;}
        public void Dispose(){if(!retained&&stream!=null)stream.Dispose();}
    }
    static Dictionary<string,object> Guard(Device device) {
        if(!Equal(device.Read(0,512),recipe.Mbr))throw new InvalidDataException("MBR changed");
        byte[] observed=device.Read(recipe.PartitionOffset,recipe.Firmware.Length);
        byte[] payload=new byte[recipe.PayloadBytes];Buffer.BlockCopy(observed,recipe.PayloadOffset,payload,0,payload.Length);if(Hash(payload)!=recipe.PayloadHash)throw new InvalidDataException("Original payload changed");
        if(!SliceEqual(observed,recipe.DirectoryOffset,recipe.Directory))throw new InvalidDataException("Installed directory differs");
        var predecessors=new List<object>();
        for(int i=0;i<recipe.Regions.Length;i++){var r=recipe.Regions[i];bool candidate=SliceEqual(observed,r.Offset,r.Data);if(!candidate&&!Zero(observed,r.Offset,r.Data.Length))throw new InvalidDataException("Staging bytes differ");if(i==recipe.Regions.Length-1&&!candidate)throw new InvalidDataException("Current candidate missing");if(i<recipe.Regions.Length-1)predecessors.Add(D("sha256",r.Hash,"staging",candidate?"candidate":"zero"));Array.Clear(observed,r.Offset,r.Data.Length);}
        Buffer.BlockCopy(recipe.Firmware,recipe.DirectoryOffset,observed,recipe.DirectoryOffset,512);
        if(Hash(observed)!=recipe.FirmwareHash)throw new InvalidDataException("Firmware differs outside pinned regions");
        return D("directory","candidate","staging","candidate","original_payload_intact",true,"predecessor_staging",predecessors);
    }
    static string Envelope(string id,Dictionary<string,object> result){return Json.Serialize(D("request_id",id,"result",result));}
    static void Save(Record record,string id){record.Response=Envelope(id,record.Receipt);}
    static void Refresh(Record record,string id,int disk) {
        var receipt=record.Receipt;receipt["operation"]="refresh-installed-directory";receipt["phase"]="identify";Save(record,id);
        try {
            var identity=Identity(disk);receipt["device"]=identity;
            using(var device=new Device(disk)) {
                receipt["phase"]="guard-before";Save(record,id);receipt["before"]=Guard(device);
                if(Canonical(identity)!=Canonical(Identity(disk)))throw new InvalidDataException("Identity changed before write");
                var write=D("offset",recipe.DiskDirectoryOffset,"bytes",512,"sha256",Hash(recipe.Directory),"complete",false);
                receipt["writes"]=new object[]{write};receipt["device_write_attempted"]=true;receipt["phase"]="refresh-identical-directory";Save(record,id);
                device.Write(recipe.DiskDirectoryOffset,recipe.Directory);write["returned_bytes"]=512;device.Flush();
                if(!Equal(device.Read(recipe.DiskDirectoryOffset,512),recipe.Directory))throw new IOException("Directory readback differs");write["complete"]=true;
                receipt["phase"]="guard-after";Save(record,id);receipt["after"]=Guard(device);
                if(Canonical(receipt["before"])!=Canonical(receipt["after"]))throw new InvalidDataException("Firmware state changed");
            }
            receipt["passed"]=true;receipt["phase"]="complete";receipt["bytes_changed"]=0;
        }catch(Exception e){receipt["failure"]=e.GetType().Name+": "+e.Message;if((bool)receipt["device_write_attempted"])poisoned=true;}
        receipt["finished_at"]=Now();Save(record,id);
    }
    static byte[] ReadExact(Stream stream,int length){byte[] b=new byte[length];int n=0;while(n<length){int got=stream.Read(b,n,length-n);if(got==0)throw new EndOfStreamException();n+=got;}return b;}
    static string Dispatch(Dictionary<string,object> request) {
        string supplied=Text(request,"token"),id=Text(request,"request_id"),op=Text(request,"op");
        if(!Equal(DecodeHash(supplied),secret))throw new UnauthorizedAccessException("Authentication failed");
        if(!Hex(id,32)||id!=id.ToLowerInvariant())throw new InvalidDataException("request_id must be32 lowercase hex");
        if(request.Count!=4)throw new InvalidDataException("Unexpected request fields");int disk=checked((int)Number(request,"disk_number"));if(disk<0||disk>1024)throw new InvalidDataException("Disk number");
        if(op!="status"&&op!="refresh"&&op!="stop")throw new InvalidDataException("Unsupported operation");
        Record existing;if(Records.TryGetValue(id,out existing)){if(existing.Op!=op||existing.Disk!=disk)throw new InvalidDataException("request_id reused with different operation");return existing.Response;}
        if(op=="status"||op=="stop"){
            if(op=="stop")stopping=true;
            return Envelope(id,D("operation",op,"passed",true,"phase","complete","plan",recipe.PlanPath,"plan_sha256",recipe.PlanHash,"serial",recipe.Serial,"usbserial",recipe.UsbSerial,"boot_build_id",recipe.BuildId,"poisoned",poisoned,"records",Records.Count,"finished_at",Now()));
        }
        if(Records.Count>=128)return Envelope(id,D("passed",false,"failure","Session receipt capacity reached"));
        var record=new Record{Op=op,Disk=disk,Receipt=D("operation",op,"passed",false,"phase","admitted","device_write_attempted",false,"writes",new object[0],"plan",recipe.PlanPath,"plan_sha256",recipe.PlanHash,"idempotency_id",id,"started_at",Now())};
        Save(record,id);Records.Add(id,record);
        if(poisoned){record.Receipt["failure"]="Session poisoned by uncertain I/O; no new refresh admitted";Save(record,id);}else Refresh(record,id,disk);
        return record.Response;
    }
    public static int Main(string[] args) {
        try {
            if(Environment.OSVersion.Platform!=PlatformID.Win32NT||!new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))throw new UnauthorizedAccessException("Elevated Windows token required");
            if(args.Length!=8)throw new ArgumentException("Exactly --recipe --recipe-sha256 --port --token required");var options=new Dictionary<string,string>();for(int i=0;i<args.Length;i+=2)options.Add(args[i],args[i+1]);
            foreach(string key in options.Keys)if(key!="--recipe"&&key!="--recipe-sha256"&&key!="--port"&&key!="--token")throw new ArgumentException("Unknown argument");
            int port;if(!Int32.TryParse(options["--port"],out port)||port<1024||port>65535)throw new ArgumentException("Port range");secret=DecodeHash(options["--token"]);recipe=Load(options["--recipe"],options["--recipe-sha256"]);
            var listener=new TcpListener(IPAddress.Loopback,port);listener.ExclusiveAddressUse=true;listener.Start(4);Console.WriteLine(Json.Serialize(D("ready",true,"port",port,"plan_sha256",recipe.PlanHash,"serial",recipe.Serial,"boot_build_id",recipe.BuildId)));
            var lifetime=Stopwatch.StartNew();try{while(!stopping&&lifetime.Elapsed.TotalHours<8){if(!listener.Pending()){Thread.Sleep(50);continue;}
                using(var client=listener.AcceptTcpClient()){client.ReceiveTimeout=client.SendTimeout=10000;using(var stream=client.GetStream()){string response;
                    try{byte[] prefix=ReadExact(stream,4);uint count=(uint)prefix[0]|(uint)prefix[1]<<8|(uint)prefix[2]<<16|(uint)prefix[3]<<24;if(count==0||count>1024)throw new InvalidDataException("Request size");response=Dispatch(Object(Json.DeserializeObject(Utf8.GetString(ReadExact(stream,(int)count)))));}
                    catch(Exception e){response=Envelope("",D("passed",false,"failure",e.GetType().Name+": "+e.Message));}
                    try{byte[] b=Utf8.GetBytes(response);stream.Write(BitConverter.GetBytes(b.Length),0,4);stream.Write(b,0,b.Length);stream.Flush();}catch(IOException){}
                }}
            }}finally{listener.Stop();}
            return 0;
        }catch(Exception e){Console.Error.WriteLine(e.GetType().Name+": "+e.Message);return 1;}
    }
}

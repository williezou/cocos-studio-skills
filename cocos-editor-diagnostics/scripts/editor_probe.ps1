$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'

function Exception-Chain($errorValue) {
    $items=New-Object 'Collections.Generic.List[string]'
    $exception=$errorValue.Exception
    while($null -ne $exception){$items.Add($exception.Message);$exception=$exception.InnerException}
    return ,$items.ToArray()
}

function Safe-Path([string]$root,[string]$relative) {
    $base=[IO.Path]::GetFullPath($root).TrimEnd('\')
    $path=[IO.Path]::GetFullPath((Join-Path $base $relative))
    if(!$path.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Reference escapes resource root'}
    return $path
}

function Read-EditorLogs($roots) {
    $found=New-Object 'Collections.Generic.List[object]'
    $queue=New-Object 'Collections.Generic.Queue[object]'
    foreach($root in $roots){if(Test-Path -LiteralPath $root -PathType Container){$queue.Enqueue(@{Path=$root;Depth=0})}}
    $visited=0
    while($queue.Count -gt 0 -and $visited -lt 800){
        $entry=$queue.Dequeue();$visited++
        foreach($item in Get-ChildItem -LiteralPath $entry.Path -Force -ErrorAction SilentlyContinue){
            if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){continue}
            if($item.PSIsContainer){
                if($item.Name -in @('Cache','GPUCache','Code Cache','Local Storage','Session Storage')){continue}
                if($entry.Depth -lt 3){$queue.Enqueue(@{Path=$item.FullName;Depth=$entry.Depth+1})};continue
            }
            if($item.Name -match '\.log($|\.)|error.*\.txt$|exception.*\.txt$' -or $item.DirectoryName -match '\\logs?$'){
                $found.Add($item)
            }
        }
    }
    $logs=@()
    foreach($item in $found | Sort-Object LastWriteTime -Descending | Select-Object -First 2){
        $lines=@(Get-Content -LiteralPath $item.FullName -Tail 60 -ErrorAction SilentlyContinue)
        $logs+=@{path=$item.FullName;modified=$item.LastWriteTime.ToString('o');tail=$lines}
    }
    return ,$logs
}

$report=@{mode='windows';files=@();validation='Only editor data parsing/type checks; not GUI import, rendering, export or resource registration verification'}
try {
    $config=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ConfigurationBase64))|ConvertFrom-Json
    $directory=[IO.Path]::GetFullPath($config.EditorDir)
    if(!(Test-Path -LiteralPath (Join-Path $directory 'CocoStudio.Model.dll'))){throw 'CocoStudio.Model.dll not found; confirm editor directory'}
    [Environment]::CurrentDirectory=$directory
    $report.editor=@{directory=$directory;process_bits=([IntPtr]::Size*8)}
    if(Test-Path -LiteralPath (Join-Path $directory 'CocosStudio.exe')){
        $report.editor.version=(Get-Item -LiteralPath (Join-Path $directory 'CocosStudio.exe')).VersionInfo.FileVersion
    }
    if([IntPtr]::Size -ne 4){throw 'This Cocos Studio probe requires 32-bit Windows PowerShell, not the default 64-bit process'}
    $modelAssembly=[Reflection.Assembly]::LoadFrom((Join-Path $directory 'CocoStudio.Model.dll'))
    $null=[Reflection.Assembly]::LoadFrom((Join-Path $directory 'CocoStudio.Projects.dll'))
    try{$modelTypes=$modelAssembly.GetTypes()}catch{
        $exception=$_.Exception;while($exception.InnerException){$exception=$exception.InnerException}
        if($null -eq $exception.Types){throw}
        $modelTypes=@($exception.Types|Where-Object {$null -ne $_})
        $report.type_loader_warnings=@($exception.LoaderExceptions|Select-Object -First 3|ForEach-Object {$_.Message})
    }
    $context=New-Object MonoDevelop.Core.Serialization.DataContext
    $baseType=$modelAssembly.GetType('CocoStudio.Model.DataModel.BaseObjectData')
    $registrationFailures=0
    foreach($type in $modelTypes){
        if(!$type.IsPublic -or !$type.IsClass -or !$baseType.IsAssignableFrom($type)){continue}
        try{$null=$context.IncludeType($type)}catch{$registrationFailures++}
    }
    $serializer=New-Object MonoDevelop.Core.Serialization.XmlDataSerializer($context)
    $dataType=$modelAssembly.GetType('CocoStudio.Model.DataModel.GameFileData')
    $scrollType=$modelAssembly.GetType('CocoStudio.Model.DataModel.ScrollViewObjectData')
    $sizeType=$scrollType.GetProperty('InnerNodeSize').PropertyType
    $report.editor.inner_size_type=@{Width=$sizeType.GetProperty('Width').PropertyType.FullName;Height=$sizeType.GetProperty('Height').PropertyType.FullName}
    $report.editor.bar_enabled_in_model=($null -ne $scrollType.GetProperty('BarEnabled'))
    $report.editor.registration_failures=$registrationFailures
    $probeDocument=$null
    foreach($relative in $config.Files){
        $file=@{file=$relative;issues=@();references=@()}
        $report.files+=,$file
        $path=Safe-Path $config.Root $relative
        if(!(Test-Path -LiteralPath $path -PathType Leaf)){$file.status='missing_file';continue}
        $file.bytes=(Get-Item -LiteralPath $path).Length
        try{
            $document=New-Object Xml.XmlDocument
            $document.LoadXml([IO.File]::ReadAllText($path,[Text.Encoding]::UTF8))
        }catch{$file.status='xml_error';$file.exception_chain=Exception-Chain $_;continue}
        if($config.SelfTest -and $null -eq $probeDocument -and $null -ne $document.SelectSingleNode("//AbstractNodeData[@ctype='ScrollViewObjectData']/InnerNodeSize")){
            $probeDocument=$document.CloneNode($true)
        }
        foreach($node in $document.SelectNodes("//AbstractNodeData[@ctype='ProjectNodeObjectData']")){
            $resource=$node.SelectSingleNode('FileData')
            if($null -eq $resource){$file.issues+=@{severity='error';code='invalid_reference';node=$node.GetAttribute('Name')};continue}
            $reference=$resource.GetAttribute('Path')
            try{$exists=Test-Path -LiteralPath (Safe-Path $config.Root $reference) -PathType Leaf}catch{
                $file.issues+=@{severity='error';code='invalid_reference';node=$node.GetAttribute('Name');path=$reference};continue
            }
            $file.references+=@{node=$node.GetAttribute('Name');path=$reference;exists=$exists}
            if(!$exists){$file.issues+=@{severity='error';code='missing_reference';path=$reference}}
        }
        foreach($node in $document.SelectNodes("//AbstractNodeData[@ctype='ScrollViewObjectData']")){
            if($node.HasAttribute('BarEnabled') -and !$report.editor.bar_enabled_in_model){
                $file.issues+=@{severity='warning';code='attribute_not_in_editor_model';node=$node.GetAttribute('Name');field='BarEnabled'}
            }
            $inner=$node.SelectSingleNode('InnerNodeSize')
            if($null -eq $inner){continue}
            foreach($key in @('Width','Height')){
                $property=$sizeType.GetProperty($key)
                $value=$inner.GetAttribute($key)
                try{$converter=[ComponentModel.TypeDescriptor]::GetConverter($property.PropertyType);$null=$converter.ConvertFromInvariantString($value)}catch{
                    $file.issues+=@{severity='error';code='editor_type_conversion';node=$node.GetAttribute('Name');field='InnerNodeSize.'+$key;value=$value;expected_type=$property.PropertyType.FullName;exception_chain=(Exception-Chain $_)}
                }
            }
        }
        $content=$document.SelectSingleNode('/GameFile/Content/Content')
        if($null -eq $content){$file.status='xml_error';$file.exception_chain=@('Missing /GameFile/Content/Content');continue}
        $reader=New-Object IO.StringReader($content.OuterXml)
        try{
            $parsed=$serializer.Deserialize([IO.TextReader]$reader,$dataType)
            $file.model_returned=($null -ne $parsed)
            $file.root_object_returned=($null -ne $parsed -and $null -ne $parsed.ObjectData)
            $file.status=if($file.model_returned -and $file.root_object_returned){'data_only_ok'}else{'data_only_incomplete'}
        }catch{$file.status='parse_error';$file.exception_chain=Exception-Chain $_}finally{$reader.Dispose()}
    }
    if($config.SelfTest){
        $integerProperty=$sizeType.GetProperty('Width')
        $converter=[ComponentModel.TypeDescriptor]::GetConverter($integerProperty.PropertyType)
        $probe=@{expected_type=$integerProperty.PropertyType.FullName}
        try{$null=$converter.ConvertFromInvariantString('436');$probe.integer_accepted=$true}catch{$probe.integer_accepted=$false}
        try{$null=$converter.ConvertFromInvariantString('436.0000');$probe.decimal_rejected=$false}catch{$probe.decimal_rejected=$true;$probe.exception_chain=Exception-Chain $_}
        if($null -ne $probeDocument){
            $inner=$probeDocument.SelectSingleNode("//AbstractNodeData[@ctype='ScrollViewObjectData']/InnerNodeSize")
            $inner.SetAttribute('Width','436.0000')
            $reader=New-Object IO.StringReader($probeDocument.SelectSingleNode('/GameFile/Content/Content').OuterXml)
            try{$null=$serializer.Deserialize([IO.TextReader]$reader,$dataType);$probe.malformed_document_rejected=$false}catch{
                $probe.malformed_document_rejected=$true;$probe.document_exception_chain=Exception-Chain $_
            }finally{$reader.Dispose()}
        }
        $report.self_test=$probe
    }
    if($config.Logs){
        $roots=@($directory,(Join-Path $env:USERPROFILE '.Cocos'),(Join-Path $env:APPDATA 'Cocos'),(Join-Path $env:LOCALAPPDATA 'CocosStudio'))+@($config.LogRoots)
        $report.logs=Read-EditorLogs $roots
        if($report.logs.Count -eq 0){$report.log_note='No matching log found in bounded editor-specific roots; this is not evidence of successful GUI parsing'}
    }
}catch{$report.harness_error=Exception-Chain $_}
$json=$report|ConvertTo-Json -Depth 20 -Compress
[Console]::WriteLine('CSD_DIAGNOSTICS_JSON:'+ [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))

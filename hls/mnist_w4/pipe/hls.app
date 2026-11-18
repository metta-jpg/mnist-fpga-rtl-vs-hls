<AutoPilot:project xmlns:AutoPilot="com.autoesl.autopilot.project" top="mnist_hls" name="pipe" projectType="C/C++">
    <files>
        <file name="../../tb/tb_mnist_hls.cpp" sc="0" tb="1" cflags="-Wno-unknown-pragmas" csimflags="" blackbox="false"/>
        <file name="src/weights_hls.h" sc="0" tb="false" cflags="" csimflags="" blackbox="false"/>
        <file name="src/mnist_hls.h" sc="0" tb="false" cflags="" csimflags="" blackbox="false"/>
        <file name="src/mnist_hls.cpp" sc="0" tb="false" cflags="-DVARIANT=1" csimflags="" blackbox="false"/>
    </files>
    <solutions>
        <solution name="dsp" status=""/>
        <solution name="lut" status=""/>
    </solutions>
</AutoPilot:project>

